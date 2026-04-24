#!/usr/bin/env python3
"""Check regime detection over time to understand why so few signals."""
import sys

sys.path.insert(0, "/Users/zihanma/Desktop/crypto-ai-trader")

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scripts.run_regression_backtest import FeatureCache, StrategySelector


def main():
    store_path = Path("/Users/zihanma/Desktop/crypto-ai-trader/backtest_data/candles")
    from trading.backtest.store import ParquetCandleStore
    store = ParquetCandleStore(store_path)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)

    df = store.load("BTCUSDT", "15m")
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
    print(f"Loaded {len(df)} candles")

    cache = FeatureCache(df, symbol="BTCUSDT")
    selector = StrategySelector()

    # Check regime every 1000 bars
    regime_counts = {"trend": 0, "range": 0, "volatile": 0, "unknown": 0}
    regime_changes = []

    prev_regime = None
    for i in range(59, len(df), 1000):
        ts = df["timestamp"].iloc[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        f15m, f1h, f4h = cache.get(ts, n_15m=60)
        if len(f15m) < 60:
            continue

        # Force detection
        high_15m = pd.Series([float(f.high) if f.high is not None else float(f.close) for f in f15m])
        low_15m = pd.Series([float(f.low) if f.low is not None else float(f.close) for f in f15m])
        close_15m = pd.Series([float(f.close) for f in f15m])
        regime = selector.detect_regime(high=high_15m, low=low_15m, close=close_15m)

        regime_counts[regime] = regime_counts.get(regime, 0) + 1

        if regime != prev_regime:
            regime_changes.append((i, ts, prev_regime, regime))
            prev_regime = regime

    print("\nRegime distribution:")
    for r, c in regime_counts.items():
        print(f"  {r}: {c} samples")

    print("\nRegime changes:")
    for idx, ts, prev, curr in regime_changes[:20]:
        print(f"  bar {idx} ({ts}): {prev} -> {curr}")


if __name__ == "__main__":
    main()
