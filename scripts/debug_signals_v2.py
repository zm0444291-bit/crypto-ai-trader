#!/usr/bin/env python3
"""Simulate BreakoutStrategy bar by bar to see trailing stop behavior."""
import sys

sys.path.insert(0, "/Users/zihanma/Desktop/crypto-ai-trader")

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scripts.run_regression_backtest import FeatureCache
from trading.backtest.store import ParquetCandleStore


def main():
    store_path = Path("/Users/zihanma/Desktop/crypto-ai-trader/backtest_data/candles")
    store = ParquetCandleStore(store_path)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)

    df = store.load("BTCUSDT", "15m")
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy().reset_index(drop=True)
    print(f"Loaded {len(df)} candles")

    cache = FeatureCache(df, symbol="BTCUSDT")

    # Simulate bar-by-bar with BreakoutStrategy
    from trading.strategies.active.breakout import BreakoutStrategy
    from trading.strategies.active.market_regime import detect_market_regime

    strat = BreakoutStrategy(lookback=20, trailing_stop_pct=0.02, max_holding_bars=48)

    in_pos = False
    entry_price = 0.0
    trades = []

    # Skip first 100 bars (warmup)
    for i in range(100, len(df)):
        ts = df["timestamp"].iloc[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        # Get features for this bar
        f15m, f1h, f4h = cache.get(ts, n_15m=60)
        if len(f15m) < 60:
            continue

        # Build DataFrame
        high_s = pd.Series([float(f.high) if f.high is not None else float(f.close) for f in f15m])
        low_s = pd.Series([float(f.low) if f.low is not None else float(f.close) for f in f15m])
        close_s = pd.Series([float(f.close) for f in f15m])
        window_df = pd.DataFrame({
            "high": high_s.values,
            "low": low_s.values,
            "close": close_s.values,
            "volume": [1.0] * len(f15m),
        })

        # Check regime for context
        regime_info = detect_market_regime(
            high=high_s, low=low_s, close=close_s,
            adx_period=14, bb_period=20, bb_std=2.0
        )
        regime = regime_info["regime"]

        # Check state BEFORE calling generate_signals
        was_in_pos = strat._in_position.get("BTCUSDT", False)

        # Generate signals
        signals = strat.generate_signals("BTCUSDT", window_df)

        for sig in signals:
            print(f"Bar {i} ({ts}): {sig.side.upper()} — regime={regime}, was_in_pos={was_in_pos}")
            if sig.side.lower() == "buy":
                entry_price = close_s.iloc[-1]
                print(f"  >>> ENTER at ${entry_price:.2f}")
            else:
                bars_held = strat._bars_held.get("BTCUSDT", 0)
                high_since = strat._high_since_entry.get("BTCUSDT", 0.0)
                pnl_pct = (close_s.iloc[-1] / entry_price - 1) * 100
                print(f"  >>> EXIT at ${close_s.iloc[-1]:.2f}, PnL={pnl_pct:.2f}%, bars_held={bars_held}, high_since=${high_since:.2f}")
                trades.append({"i": i, "ts": ts, "pnl_pct": pnl_pct, "bars_held": bars_held})

        in_pos_now = strat._in_position.get("BTCUSDT", False)
        if i % 5000 == 0 and i > 100:
            bars_held = strat._bars_held.get("BTCUSDT", 0)
            high_since = strat._high_since_entry.get("BTCUSDT", 0.0)
            stop_level = high_since * (1 - 0.02) if high_since > 0 else 0
            print(f"  Bar {i} ({ts}): close=${close_s.iloc[-1]:.2f}, in_pos={in_pos_now}, bars_held={bars_held}, high_since=${high_since:.2f}, stop=${stop_level:.2f}, regime={regime}")

    print(f"\nTotal trades: {len(trades)}")
    for t in trades:
        print(f"  {t['ts']} — PnL={t['pnl_pct']:.2f}%, bars_held={t['bars_held']}")

if __name__ == "__main__":
    main()
