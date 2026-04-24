"""Multi-strategy backtest across BTC, Gold, EURUSD, GBPUSD.

Goal: Find consistently profitable strategies across instruments.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


@dataclass
class Signal:
    qty: Decimal
    side: str  # "buy" or "sell"
    entry_atr: float | None = None


# ─── Strategy Library ───────────────────────────────────────────────────────────

class EMACrossover:
    """Fast/Slow EMA crossover — classic trend filter."""

    def __init__(self, fast: int = 20, slow: int = 50):
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


class DonchianBreakout:
    """Donchian Channel breakout — rides strong trends."""

    def __init__(self, lookback: int = 20):
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


class RSIMeanReversion:
    """RSI extreme zone reversion — buy oversold, sell overbought."""

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
    """EMA triple filter — only trade in direction of 3 EMAs."""

    def __init__(self, short: int = 20, mid: int = 50, long: int = 200):
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


class ATRTrendFollower:
    """Trend follower using ATR for stops — rides trends with mechanical exits."""

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

        entry_bar = bool(close.iloc[-1] > close.ewm(span=20, adjust=False).mean().iloc[-1])

        if not in_pos and entry_bar:
            self._in_pos[symbol] = {"entry": float(close.iloc[-1]), "atr": atr}
            return [Signal(qty=Decimal("1"), side="buy", entry_atr=atr)]

        if in_pos:
            # Hard stop
            stop = entry_price - self.mult * entry_atr
            # Trailing ATR stop
            if float(close.iloc[-1]) < stop:
                del self._in_pos[symbol]
                return [Signal(qty=Decimal("1"), side="sell")]
        return []


class SessionFilter:
    """Wraps any strategy to only trade during high-volume sessions."""

    def __init__(self, inner, us_session_only: bool = True):
        self.inner = inner
        self.us_session_only = us_session_only

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        if len(df) < 2:
            return []
        ts = df["timestamp"].iloc[-1]
        if hasattr(ts, 'hour'):
            hour = ts.hour
        else:
            hour = pd.Timestamp(ts).hour
        # US session: 13:30-21:00 UTC (overlap of NY London)
        if self.us_session_only and not (13 <= hour < 21):
            return []
        signals: list[Signal] = self.inner.generate_signals(symbol, df)
        return signals


# ─── Run backtest ──────────────────────────────────────────────────────────────

STRATEGIES = {
    "EMA(20,50)":          EMACrossover(20, 50),
    "EMA(10,50)":          EMACrossover(10, 50),
    "EMA(5,21)":           EMACrossover(5, 21),
    "Donchian(20)":        DonchianBreakout(20),
    "Donchian(50)":        DonchianBreakout(50),
    "RSI(14,30/70)":       RSIMeanReversion(14, 30, 70),
    "RSI(7,25/75)":        RSIMeanReversion(7, 25, 75),
    "EMA_Triple":           EMATrendFilter(20, 50, 200),
    "ATR_Trend(2x)":        ATRTrendFollower(14, 2.0),
    "EMA(20,50)+US_Sess":  SessionFilter(EMACrossover(20, 50), us_session_only=True),
    "EMA(10,50)+US_Sess":  SessionFilter(EMACrossover(10, 50), us_session_only=True),
    "RSI(14)+US_Sess":     SessionFilter(RSIMeanReversion(14, 30, 70), us_session_only=True),
}

INSTRUMENTS = {
    "BTCUSDT": ("btcusdt", "1h"),
    "XAUUSD":  ("xauusd",  "1h"),
    "EURUSD":  ("eurusd",  "1h"),
    "GBPUSD":  ("gbpusd",  "1h"),
}


@dataclass
class Result:
    instrument: str
    strategy: str
    total_trades: int
    total_return_pct: float
    sharpe: float
    max_dd_pct: float
    win_rate: float


def run() -> list[Result]:
    store = ParquetCandleStore(Path("backtest_data/candles"))
    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("1")},  # forex tight spread
        initial_equity=Decimal("10_000"),
        interval="1h",
    )
    results: list[Result] = []

    for instr_name, (store_sym, interval) in INSTRUMENTS.items():
        if not store.exists(store_sym, interval):
            print(f"[SKIP] {instr_name}: no data for {store_sym}/{interval}")
            continue

        for strat_name, strategy in STRATEGIES.items():
            try:
                result = BacktestEngine(config, store).run(
                    strategy=strategy,
                    symbols=[instr_name],
                    start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    end_time=datetime(2025, 12, 31, tzinfo=timezone.utc),
                )
                results.append(Result(
                    instrument=instr_name,
                    strategy=strat_name,
                    total_trades=result.total_trades,
                    total_return_pct=float(result.total_return_pct),
                    sharpe=float(result.sharpe_ratio),
                    max_dd_pct=float(result.max_drawdown_pct),
                    win_rate=float(result.win_rate),
                ))
            except Exception as e:
                print(f"[ERROR] {instr_name}/{strat_name}: {e}")

    return results


def print_results(results: list[Result]):
    # Overall ranking
    results.sort(key=lambda r: r.sharpe, reverse=True)

    print(f"\n{'Instr':<15} {'Strategy':<25} {'Trades':>6} {'Return%':>8} {'Sharpe':>7} {'MaxDD%':>7} {'Win%':>6}")
    print("-" * 80)
    for r in results:
        print(
            f"{r.instrument:<15} {r.strategy:<25} {r.total_trades:>6} "
            f"{r.total_return_pct:>8.1f} {r.sharpe:>7.3f} "
            f"{r.max_dd_pct:>7.1f} {r.win_rate:>6.1f}"
        )

    print("\n=== TOP 5 by Sharpe ===")
    for r in results[:5]:
        print(f"  {r.instrument}/{r.strategy}: Sharpe={r.sharpe:.3f}, Ret={r.total_return_pct:.1f}%, Trades={r.total_trades}")

    # Per-instrument best
    print("\n=== Best per Instrument ===")
    for instr in {r.instrument for r in results}:
        best = sorted([r for r in results if r.instrument == instr], key=lambda x: x.sharpe, reverse=True)[0]
        print(f"  {instr}: {best.strategy} (Sharpe={best.sharpe:.3f}, Ret={best.total_return_pct:.1f}%)")


if __name__ == "__main__":
    results = run()
    print_results(results)
