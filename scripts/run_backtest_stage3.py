"""Backtest runner using Stage 3 real strategies — Breakout + MeanReversion + RegimeRouting.

Key design:
  - Pre-compute CandleFeatures ONCE for the full dataset (avoid O(n²) rebuild)
  - Strategy manages its own position state (no set_in_position hook)
  - BacktestEngine.run() handles bar iteration and execution only
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore
from trading.features.builder import (  # type: ignore[attr-defined]
    CandleData,
    CandleFeatures,
    build_features,
)
from trading.strategies.active.breakout import BreakoutStrategy
from trading.strategies.active.mean_reversion import MeanReversionStrategy
from trading.strategies.base import Signal as BaseSignal

UTC = UTC


@dataclass
class Signal:
    qty: Decimal
    side: str
    entry_atr: float | None = None


class Stage3Adapter:
    """Breakout + MeanReversion with regime routing. Manages its own position state.

    The BacktestEngine calls generate_signals() each bar. We pre-compute features
    once in __init__, then slice per-bar to avoid O(n²) rebuild costs.
    """

    STRATEGY_NAME: str = "Stage3Adapter"

    def __init__(
        self,
        breakout: BreakoutStrategy | None = None,
        mean_rev: MeanReversionStrategy | None = None,
    ):
        self._breakout = breakout or BreakoutStrategy(
            lookback=20,
            regime_adx_threshold=25.0,
            min_confidence=0.6,
            trailing_stop_pct=0.02,
            max_holding_bars=96,
        )
        self._mean_rev = mean_rev or MeanReversionStrategy(
            bb_period=20,
            bb_std=2.0,
            regime_adx_threshold=25.0,
            min_confidence=0.6,
        )
        self._in_position: dict[str, bool] = {}
        self._features: dict[str, list[CandleFeatures]] = {}
        self._built: bool = False

    def build_features(self, symbol: str, df: pd.DataFrame) -> None:
        """Pre-compute features for the full DataFrame once. Call before engine.run()."""
        candles: list[CandleData] = []
        for _, row in df.iterrows():
            candles.append(
                CandleData(
                    symbol=symbol,
                    timeframe="1h",
                    open_time=row["timestamp"],
                    close_time=row["timestamp"],
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(row.get("volume", 1.0))),
                    source="backtest",
                )
            )
        self._features[symbol] = build_features(candles)
        self._built = True

    def generate_signals(
        self, symbol: str, df: pd.DataFrame
    ) -> list[Signal]:
        """Called by BacktestEngine each bar. Uses pre-computed features."""
        if not self._built or symbol not in self._features:
            return []
        all_features = self._features[symbol]

        n = len(df)
        if n > len(all_features):
            return []
        if n < 22:
            return []

        # Slice features to match this bar window
        features = all_features[:n]

        # Build OHLCV series from features
        high_vals: list[float] = []
        low_vals: list[float] = []
        close_vals: list[float] = []
        vol_vals: list[float] = []
        for f in features:
            close_vals.append(float(f.close))
            high_vals.append(float(f.high) if f.high is not None else float(f.close))
            low_vals.append(float(f.low) if f.low is not None else float(f.close))
            vol_vals.append(float(f.volume_ratio) if f.volume_ratio is not None else 1.0)

        high_s = pd.Series(high_vals)
        low_s = pd.Series(low_vals)
        close_s = pd.Series(close_vals)
        vol_s = pd.Series(vol_vals)

        feat_df = pd.DataFrame(
            {"high": high_s, "low": low_s, "close": close_s, "volume": vol_s},
            index=range(len(features)),
        )

        in_pos = self._in_position.get(symbol, False)

        # ── Regime detection ─────────────────────────────────────────────
        regime_info = self._detect_regime(high_s, low_s, close_s)
        regime = regime_info.get("regime", "trend")

        # ── Select strategy ──────────────────────────────────────────────
        if regime == "range":
            strategy: BreakoutStrategy | MeanReversionStrategy = self._mean_rev
        else:
            strategy = self._breakout

        # ── Generate signals ─────────────────────────────────────────────
        try:
            base_signals: list[BaseSignal] = strategy.generate_signals(symbol, feat_df)
        except Exception:
            return []

        signals = []
        for bs in base_signals:
            bs_side = bs.side.lower()
            if not in_pos and bs_side == "buy":
                self._in_position[symbol] = True
                signals.append(
                    Signal(qty=Decimal("1"), side="buy", entry_atr=bs.entry_atr)
                )
                in_pos = True
            elif in_pos and bs_side == "sell":
                self._in_position[symbol] = False
                signals.append(Signal(qty=Decimal("1"), side="sell"))
                in_pos = False

        return signals

    def _detect_regime(
        self, high: pd.Series, low: pd.Series, close: pd.Series
    ) -> dict[str, Any]:
        from trading.strategies.active.market_regime import detect_market_regime

        try:
            result = detect_market_regime(
                high=high,
                low=low,
                close=close,
                adx_period=14,
                bb_period=20,
                bb_std=2.0,
                adx_strong_threshold=25.0,
                bb_narrow_threshold=0.04,
            )
            regime_val = result["regime"]
            return {"regime": regime_val}
        except Exception:
            return {"regime": "trend"}

    def set_in_position(self, symbol: str, in_pos: bool) -> None:
        # BacktestEngine calls this after each bar to sync the engine's
        # book-of-record with the strategy's internal state.
        self._in_position[symbol] = in_pos
        self._breakout._in_position[symbol] = in_pos
        self._mean_rev._in_position[symbol] = in_pos


def run() -> None:
    store = ParquetCandleStore(Path("backtest_data/candles"))
    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10_000"),
        interval="1h",
    )

    adapter = Stage3Adapter()

    # ── Pre-compute features once for BTCUSDT 2025 ──────────────────────
    raw_df = store.load("BTCUSDT", "1h")
    if raw_df is None:
        raise ValueError("No data loaded for BTCUSDT")
    _start = datetime(2025, 1, 1, tzinfo=UTC)
    _end = datetime(2026, 1, 1, tzinfo=UTC)
    df = raw_df[
        (raw_df["timestamp"] >= _start) & (raw_df["timestamp"] <= _end)
    ].reset_index(drop=True)
    print(f"Loaded {len(df)} bars for BTCUSDT 2025")
    adapter.build_features("BTCUSDT", df)

    engine = BacktestEngine(config, store)

    print("Running backtest with Stage 3 strategies...")
    print("  Strategies: Breakout + MeanReversion via RegimeRouting")
    print("  Period: 2025-01-01 to 2026-01-01")
    print()

    result = engine.run(
        strategy=adapter,
        symbols=["BTCUSDT"],
        start_time=datetime(2025, 1, 1),
        end_time=datetime(2026, 1, 1),
    )

    print("=" * 60)
    print("BACKTEST REPORT — BTCUSDT 1h — 2025")
    print("Strategy: Stage 3 — Breakout + MeanReversion + RegimeRouting")
    print("=" * 60)
    print(f"  Initial Equity : ${result.initial_equity:,.2f}")
    print(f"  Final Equity   : ${result.final_equity:,.2f}")
    print(f"  Total Return   : {result.total_return_pct:.2f}%")
    print(f"  Sharpe Ratio   : {result.sharpe_ratio:.3f}")
    print(f"  Max Drawdown   : {result.max_drawdown_pct:.2f}%")
    print(f"  Win Rate       : {result.win_rate:.1%}")
    print(f"  Total Trades   : {result.total_trades}")
    if result.total_trades > 0:
        print(f"  Avg Win        : ${result.avg_win:,.2f}")
        print(f"  Avg Loss       : ${result.avg_loss:,.2f}")
    print()
    print("  All trades:")
    for t in result.trades:
        pnl = t.get("pnl")
        pnl_str = f"${pnl:,.2f}" if pnl is not None else "—"
        price: Any = t.get("entry_price") or t.get("exit_price")
        ts_str = str(t.get("timestamp", ""))[:19]
        fee_val = float(t.get("fee", 0) or 0)
        print(
            f"    {ts_str}  "
            f"{str(t['side']).upper():4s}  "
            f"qty={float(t['qty']):.6f}  "
            f"price=${float(price):.2f}  "
            f"fee=${fee_val:.4f}  "
            f"pnl={pnl_str}"
        )


if __name__ == "__main__":
    run()
