"""Strategy parameter sensitivity scanner — precomputed regime version.

Precomputes ADX and Bollinger Bandwidth once over the full dataset,
then simulates strategy performance for each parameter combination
without re-running the expensive indicator calculations.

This makes the grid scan O(1) per combination instead of O(n²).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass as dc
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore
from trading.events.economic_calendar import EconomicCalendar
from trading.features.builder import CandleFeatures
from trading.strategies.active.strategy_selector import StrategySelector


# ─── Signal (matches backtest engine's duck-type contract) ──────────────────────

@dc
class Signal:
    qty: Decimal
    side: str  # "buy" or "sell"
    entry_atr: float | None = None


# ─── Regime precomputer ─────────────────────────────────────────────────────────
#
# Runs detect_market_regime once over the full price series, storing
# regime + all component metrics per bar so each param-grid combination
# can be re-evaluated without recomputing indicators.

def _rolling_regime(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    adx_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pd.DataFrame:
    """Compute ADX and Bollinger Bandwidth rolling over full series.

    Returns a DataFrame with columns: adx, bb_bandwidth, regime
    for every bar index where sufficient history exists.
    """
    n = len(close)
    adx_vals = np.full(n, np.nan)
    bw_vals = np.full(n, np.nan)

    # ── True Range ─────────────────────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)

    smooth_tr = tr.rolling(adx_period, min_periods=adx_period).sum()
    smooth_plus_dm = plus_dm.rolling(adx_period, min_periods=adx_period).sum()
    smooth_minus_dm = minus_dm.rolling(adx_period, min_periods=adx_period).sum()

    # ── ADX ─────────────────────────────────────────────────────────────────────
    for i in range(adx_period * 2 - 1, n):
        tr_val = smooth_tr.iloc[i]
        if tr_val <= 0:
            continue
        plus_di = 100 * smooth_plus_dm.iloc[i] / tr_val
        minus_di = 100 * smooth_minus_dm.iloc[i] / tr_val
        if plus_di + minus_di <= 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx_vals[i] = dx

    # Rolling ADX smoothing
    adx_series = pd.Series(adx_vals).replace([np.inf, -np.inf], np.nan)
    adx_smooth = adx_series.rolling(adx_period, min_periods=1).mean()

    # ── Bollinger Bandwidth ────────────────────────────────────────────────────
    mid = close.rolling(bb_period, min_periods=bb_period).mean()
    std = close.rolling(bb_period, min_periods=bb_period).std(ddof=0)
    upper = mid + bb_std * std
    lower = mid - bb_std * std
    bw = (upper - lower) / mid

    # Fill the first (bb_period-1) rows with NaN
    bw_vals[bb_period - 1:] = bw.values[bb_period - 1:]

    result = pd.DataFrame(
        {"adx": adx_smooth.values, "bb_bandwidth": bw_vals, "close": close.values},
        index=close.index,
    )
    return result


def _classify_regime(
    row: pd.Series,
    adx_strong_threshold: float,
    bb_narrow_threshold: float,
) -> str:
    adx = row["adx"]
    bw = row["bb_bandwidth"]

    if pd.isna(adx) or pd.isna(bw):
        return "range"
    if bw < bb_narrow_threshold:
        return "range"
    if adx >= adx_strong_threshold:
        return "trend"
    return "volatile"


# ─── Caching adapter with precomputed regime ─────────────────────────────────────

class PrecomputedRegimeAdapter:
    """Fast backtest adapter that uses precomputed regime data.

    Instead of recomputing ADX/BB at every bar, uses a pre-built
    regime Series (computed once over the full dataset).
    """

    def __init__(
        self,
        selector: StrategySelector,
        regime_df: pd.DataFrame,
        adx_strong_threshold: float,
        bb_narrow_threshold: float,
    ) -> None:
        self._selector = selector
        self._regime_df = regime_df
        self._adx_threshold = adx_strong_threshold
        self._bb_threshold = bb_narrow_threshold

    def generate_signals(self, symbol: str, df: pd.DataFrame):
        if len(df) < 50:
            return []

        window = df.tail(100).reset_index(drop=True)

        # Build CandleFeatures
        features_15m: list[CandleFeatures] = []
        for _, row in window.iterrows():
            ts = row["timestamp"].to_pydatetime()
            try:
                cf = CandleFeatures.model_validate({
                    "symbol": symbol,
                    "timeframe": "15m",
                    "candle_time": ts,
                    "close": Decimal(str(row["close"])),
                    "high": Decimal(str(row["high"])),
                    "low": Decimal(str(row["low"])),
                    "ema_fast": None,
                    "ema_slow": None,
                    "ema_200": None,
                    "rsi_14": None,
                    "atr_14": None,
                    "volume_ratio": None,
                    "trend_state": "unknown",
                })
                features_15m.append(cf)
            except Exception:
                continue

        if not features_15m:
            return []

        now = window.iloc[-1]["timestamp"].to_pydatetime()

        # Override regime detection with precomputed value
        last_ts = window.iloc[-1]["timestamp"]
        if last_ts in self._regime_df.index:
            regime_row = self._regime_df.loc[last_ts]
            regime = _classify_regime(
                regime_row, self._adx_threshold, self._bb_threshold
            )
            self._selector._regime_cache[symbol] = regime
        else:
            self._selector._regime_cache.clear()

        candidate = self._selector.select_candidate(
            symbol=symbol,
            features_15m=features_15m,
            features_1h=[],
            features_4h=[],
            now=now,
        )

        if candidate is None:
            return []

        return [Signal(qty=Decimal("1"), side=candidate.side.lower())]


# ─── Scan result ───────────────────────────────────────────────────────────────

@dc
class ScanResult:
    adx_threshold: float
    bb_threshold: float
    min_confidence: float
    total_trades: int
    sharpe: float
    max_dd_pct: float
    total_return_pct: float
    win_rate: float


# ─── Parameter grid ────────────────────────────────────────────────────────────

ADX_VALUES = [20.0, 25.0, 30.0, 35.0]
BB_VALUES = [0.02, 0.04, 0.06]
CONF_VALUES = [0.5, 0.6, 0.7]


def run_scan():
    store = ParquetCandleStore(Path("backtest_data/candles"))
    symbol = "BTCUSDT"

    df_all = store.load(symbol, "15m")
    if df_all is None or df_all.empty:
        print(f"No data found for {symbol} in backtest_data/candles")
        return

    start = datetime(2025, 3, 1, tzinfo=timezone.utc)
    end = datetime(2025, 6, 1, tzinfo=timezone.utc)
    df = df_all[(df_all["timestamp"] >= start) & (df_all["timestamp"] <= end)].reset_index(drop=True)
    print(f"Data: {symbol} 15m | {start.date()} → {end.date()} | {len(df)} bars")
    print(f"Grid: {len(ADX_VALUES)}×{len(BB_VALUES)}×{len(CONF_VALUES)} = {len(ADX_VALUES)*len(BB_VALUES)*len(CONF_VALUES)} runs")
    print()

    # ── Precompute regime for full series ─────────────────────────────────────
    print("Precomputing regime indicators (one-time)...")
    high = pd.Series(df["high"].values, index=df["timestamp"])
    low = pd.Series(df["low"].values, index=df["timestamp"])
    close = pd.Series(df["close"].values, index=df["timestamp"])
    regime_df = _rolling_regime(high, low, close)
    print(f"Done. Regime distribution: {regime_df['adx'].notna().sum()} valid bars")
    print()

    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("3")},
        initial_equity=Decimal("10_000"),
        interval="15m",
    )
    engine = BacktestEngine(config, store)

    results: list[ScanResult] = []

    for adx in ADX_VALUES:
        for bb in BB_VALUES:
            for conf in CONF_VALUES:
                selector = StrategySelector(
                    symbols=[symbol],
                    regime_adx_threshold=adx,
                    bb_narrow_threshold=bb,
                    min_confidence=conf,
                    economic_calendar=EconomicCalendar(),
                )

                adapter = PrecomputedRegimeAdapter(
                    selector,
                    regime_df=regime_df,
                    adx_strong_threshold=adx,
                    bb_narrow_threshold=bb,
                )

                result = engine.run(
                    strategy=adapter,
                    symbols=[symbol],
                    start_time=start,
                    end_time=end,
                    initial_equity=Decimal("10_000"),
                )

                results.append(
                    ScanResult(
                        adx_threshold=adx,
                        bb_threshold=bb,
                        min_confidence=conf,
                        total_trades=result.total_trades,
                        sharpe=float(result.sharpe_ratio),
                        max_dd_pct=float(result.max_drawdown_pct),
                        total_return_pct=float(result.total_return_pct),
                        win_rate=float(result.win_rate),
                    )
                )

    results.sort(key=lambda r: r.sharpe, reverse=True)

    print("| ADX  | BB   | Conf | Trades | Sharpe | Max DD% | Ret%  | Win%  |")
    print("|------|------|------|--------|--------|---------|-------|-------|")
    for r in results:
        print(
            f"| {r.adx_threshold:4.0f} | {r.bb_threshold:.2f} | {r.min_confidence:.1f} "
            f"| {r.total_trades:6d} | {r.sharpe:6.3f} | {r.max_dd_pct:7.2f} "
            f"| {r.total_return_pct:5.1f} | {r.win_rate:5.1f} |"
        )

    print()
    best = results[0]
    worst = results[-1]
    print(f"Best : ADX={best.adx_threshold}, BB={best.bb_threshold}, Conf={best.min_confidence}")
    print(f"      Sharpe={best.sharpe:.3f}, Trades={best.total_trades}, Ret={best.total_return_pct:.1f}%")
    print(f"Worst: ADX={worst.adx_threshold}, BB={worst.bb_threshold}, Conf={worst.min_confidence}")
    print(f"      Sharpe={worst.sharpe:.3f}, Trades={worst.total_trades}")


if __name__ == "__main__":
    run_scan()
