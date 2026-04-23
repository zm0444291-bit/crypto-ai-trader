"""Refined strategy optimization for XAUUSD + EURUSD + GBPUSD.

Findings from coarse scan:
  - XAUUSD: EMA(20,50) Sharpe=6.0, ATR_Trend Sharpe=6.3
  - EURUSD: ATR_Trend(2x) Sharpe=3.8
  - BTCUSD: RSI(14,30/70) Sharpe=2.0

Now do fine-grained parameter search on top strategies per instrument.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from itertools import product
from pathlib import Path

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


@dataclass
class Signal:
    qty: Decimal
    side: str
    entry_atr: float | None = None


# ─── Strategies ────────────────────────────────────────────────────────────────

class EMACrossover:
    def __init__(self, fast: int, slow: int):
        self.fast = fast
        self.slow = slow
        self._in_pos: dict[str, bool] = {}

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < self.slow + 2:
            return []
        closes = df["close"].astype(float)
        fast_ema = closes.ewm(span=self.fast, adjust=False).mean()
        slow_ema = closes.ewm(span=self.slow, adjust=False).mean()
        f0, s0 = fast_ema.iloc[-1], slow_ema.iloc[-1]
        f1, s1 = fast_ema.iloc[-2], slow_ema.iloc[-2]
        in_pos = self._in_pos.get(symbol, False)

        if not in_pos and f1 <= s1 and f0 > s0:
            self._in_pos[symbol] = True
            return [Signal(qty=Decimal("1"), side="buy")]
        if in_pos and f1 >= s1 and f0 < s0:
            self._in_pos[symbol] = False
            return [Signal(qty=Decimal("1"), side="sell")]
        return []


class ATRTrendFollower:
    def __init__(self, atr_period: int = 14, mult: float = 2.0):
        self.atr_period = atr_period
        self.mult = mult
        self._in_pos: dict[str, dict] = {}

    def _atr(self, high, low, close, period: int) -> float:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < self.atr_period + 2:
            return []
        high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
        atr = self._atr(high, low, close, self.atr_period)
        state = self._in_pos.get(symbol)
        in_pos = state is not None
        entry_price = state["entry"] if in_pos else None
        entry_atr = state["atr"] if in_pos else None

        bull = bool(close.iloc[-1] > close.ewm(span=20, adjust=False).mean().iloc[-1])

        if not in_pos and bull:
            self._in_pos[symbol] = {"entry": float(close.iloc[-1]), "atr": atr}
            return [Signal(qty=Decimal("1"), side="buy", entry_atr=atr)]

        if in_pos:
            stop = entry_price - self.mult * entry_atr
            if float(close.iloc[-1]) < stop:
                del self._in_pos[symbol]
                return [Signal(qty=Decimal("1"), side="sell")]
        return []


class RSIMeanReversion:
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._in_pos: dict[str, bool] = {}

    def _rsi(self, closes: pd.Series) -> float:
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = (-delta).clip(lower=0).rolling(self.period).mean()
        rs = gain / loss
        return float((100 - 100 / (1 + rs)).iloc[-1])

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < self.period + 2:
            return []
        closes = df["close"].astype(float)
        rsi = self._rsi(closes)
        in_pos = self._in_pos.get(symbol, False)

        if not in_pos and rsi < self.oversold:
            self._in_pos[symbol] = True
            return [Signal(qty=Decimal("1"), side="buy")]
        if in_pos and rsi > self.overbought:
            self._in_pos[symbol] = False
            return [Signal(qty=Decimal("1"), side="sell")]
        return []


class EMATrendFilter:
    """Triple EMA — only enter when all 3 aligned."""
    def __init__(self, short: int, mid: int, long: int):
        self.short = short
        self.mid = mid
        self.long = long
        self._in_pos: dict[str, bool] = {}

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < self.long + 2:
            return []
        closes = df["close"].astype(float)
        ema_s = closes.ewm(span=self.short, adjust=False).mean()
        ema_m = closes.ewm(span=self.mid, adjust=False).mean()
        ema_l = closes.ewm(span=self.long, adjust=False).mean()
        in_pos = self._in_pos.get(symbol, False)
        bull = bool(ema_s.iloc[-1] > ema_m.iloc[-1] > ema_l.iloc[-1])
        prev_bull = bool(ema_s.iloc[-2] > ema_m.iloc[-2] > ema_l.iloc[-2])

        if not in_pos and bull and not prev_bull:
            self._in_pos[symbol] = True
            return [Signal(qty=Decimal("1"), side="buy")]
        if in_pos and not bull and prev_bull:
            self._in_pos[symbol] = False
            return [Signal(qty=Decimal("1"), side="sell")]
        return []


class DonchianBreakout:
    def __init__(self, lookback: int):
        self.lookback = lookback
        self._in_pos: dict[str, bool] = {}

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < self.lookback + 2:
            return []
        in_pos = self._in_pos.get(symbol, False)
        high_prev = df["high"].iloc[-(self.lookback + 1) : -1].max()
        low_prev = df["low"].iloc[-(self.lookback + 1) : -1].min()
        close_now = float(df["close"].iloc[-1])
        close_prev = float(df["close"].iloc[-2])

        if not in_pos and close_now > high_prev and close_prev <= high_prev:
            self._in_pos[symbol] = True
            return [Signal(qty=Decimal("1"), side="buy")]
        if in_pos and close_now < low_prev and close_prev >= low_prev:
            self._in_pos[symbol] = False
            return [Signal(qty=Decimal("1"), side="sell")]
        return []


# ─── Instrument-specific strategy grids ───────────────────────────────────────

GRIDS = {
    "XAUUSD": {
        "EMA_Crossover": list(product([10, 15, 20, 25, 30], [40, 50, 60, 80])),
        "EMA_Triple": list(product([10, 15, 20], [30, 50], [150, 200, 250])),
        "ATR_Trend": list(product([7, 14, 21], [1.5, 2.0, 2.5, 3.0])),
        "Donchian": [(n,) for n in [10, 20, 30, 40, 50, 60, 80, 100]],
        "RSI": list(product([7, 14], [25, 30, 35], [65, 70, 75])),
    },
    "EURUSD": {
        "EMA_Crossover": list(product([10, 20, 30], [50, 80, 100])),
        "ATR_Trend": list(product([7, 14, 21], [1.5, 2.0, 2.5])),
        "RSI": list(product([14, 21], [25, 30], [70, 75])),
    },
    "GBPUSD": {
        "EMA_Crossover": list(product([10, 20, 30], [50, 80, 100])),
        "ATR_Trend": list(product([7, 14, 21], [1.5, 2.0, 2.5])),
        "RSI": list(product([14, 21], [25, 30], [70, 75])),
    },
    "BTCUSDT": {
        "RSI": list(product([7, 14, 21], [25, 30, 35], [65, 70, 75])),
        "EMA_Crossover": list(product([10, 20], [50, 100])),
    },
}

INSTRUMENTS = {
    "XAUUSD":  ("xauusd",  "1h"),
    "EURUSD":  ("eurusd",  "1h"),
    "GBPUSD":  ("gbpusd",  "1h"),
    "BTCUSDT": ("btcusdt", "1h"),
}


@dataclass
class Result:
    instrument: str
    strategy: str
    params: str
    total_trades: int
    total_return_pct: float
    sharpe: float
    max_dd_pct: float
    win_rate: float


def run_grid(instr: str, strat_name: str, params_list: list, make_strategy, store, config) -> list[Result]:
    results = []
    for params in params_list:
        strategy = make_strategy(*params) if params else make_strategy()
        try:
            res = BacktestEngine(config, store).run(
                strategy=strategy,
                symbols=[instr],
                start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end_time=datetime(2025, 12, 31, tzinfo=timezone.utc),
            )
            results.append(Result(
                instrument=instr,
                strategy=strat_name,
                params=str(params),
                total_trades=res.total_trades,
                total_return_pct=float(res.total_return_pct),
                sharpe=float(res.sharpe_ratio),
                max_dd_pct=float(res.max_drawdown_pct),
                win_rate=float(res.win_rate),
            ))
        except Exception:
            pass  # skip bad params silently
    return results


def make_ema(fast: int, slow: int) -> EMACrossover:
    return EMACrossover(fast, slow)


def make_atr(period: int, mult: float) -> ATRTrendFollower:
    return ATRTrendFollower(period, mult)


def make_rsi(period: int, oversold: float, overbought: float) -> RSIMeanReversion:
    return RSIMeanReversion(period, oversold, overbought)


def make_triple(short: int, mid: int, long: int) -> EMATrendFilter:
    return EMATrendFilter(short, mid, long)


def make_donchian(lookback: int) -> DonchianBreakout:
    return DonchianBreakout(lookback)


def run() -> list[Result]:
    store = ParquetCandleStore(Path("backtest_data/candles"))
    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("1")},
        initial_equity=Decimal("10_000"),
        interval="1h",
    )

    all_results: list[Result] = []

    for instr, (store_sym, interval) in INSTRUMENTS.items():
        if not store.exists(store_sym, interval):
            print(f"[SKIP] {instr}")
            continue
        print(f"\n=== {instr} ===")
        grids = GRIDS.get(instr, {})

        for strat_name, params_list in grids.items():
            strat_results: list[Result] = []
            if strat_name == "EMA_Crossover":
                strat_results = run_grid(instr, strat_name, params_list, make_ema, store, config)
            elif strat_name == "ATR_Trend":
                strat_results = run_grid(instr, strat_name, params_list, make_atr, store, config)
            elif strat_name == "RSI":
                strat_results = run_grid(instr, strat_name, params_list, make_rsi, store, config)
            elif strat_name == "EMA_Triple":
                strat_results = run_grid(instr, strat_name, params_list, make_triple, store, config)
            elif strat_name == "Donchian":
                strat_results = run_grid(instr, strat_name, params_list, make_donchian, store, config)

            if strat_results:
                strat_results.sort(key=lambda r: r.sharpe, reverse=True)
                best = strat_results[0]
                print(f"  {strat_name}: best={best.params} Sharpe={best.sharpe:.3f} Ret={best.total_return_pct:.1f}% Trades={best.total_trades}")
                all_results.extend(strat_results)

    return all_results


def print_all(results: list[Result]):
    results.sort(key=lambda r: r.sharpe, reverse=True)
    print(f"\n{'Instr':<10} {'Strategy':<12} {'Params':<35} {'Trades':>6} {'Ret%':>7} {'Sharpe':>7} {'MaxDD%':>7} {'Win%':>6}")
    print("-" * 100)
    for r in results:
        print(f"{r.instrument:<10} {r.strategy:<12} {r.params:<35} {r.total_trades:>6} {r.total_return_pct:>7.1f} {r.sharpe:>7.3f} {r.max_dd_pct:>7.1f} {r.win_rate:>6.1f}")

    print("\n=== TOP 10 ===")
    for r in results[:10]:
        print(f"  {r.instrument}/{r.strategy}{r.params}: Sharpe={r.sharpe:.3f} Ret={r.total_return_pct:.1f}% MaxDD={r.max_dd_pct:.1f}% Trades={r.total_trades}")


if __name__ == "__main__":
    results = run()
    print_all(results)
