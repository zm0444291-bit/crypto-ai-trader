#!/usr/bin/env python3
"""诊断信号为什么这么少 — 按月统计 regime 分布和信号数"""
import sys

sys.path.insert(0, ".")

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_regression_backtest import BacktestAdapter, FeatureCache
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector


def main():
    store = ParquetCandleStore(Path("backtest_data/candles"))
    df = store.load("BTCUSDT", "15m")

    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 12, 31, tzinfo=UTC)
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
    print(f"Loaded {len(df)} candles")

    cache = FeatureCache(df, symbol="BTCUSDT")
    selector = StrategySelector()
    adapter = BacktestAdapter(cache, selector)

    # Simulate bar-by-bar, collect stats
    regimes = Counter()
    regime_with_signal = Counter()
    signals_per_month = Counter()
    monthly = {}

    bars_15m = df.reset_index(drop=True)
    n = len(bars_15m)

    for i in range(n):
        ts = bars_15m["timestamp"].iloc[i]
        bar_df = bars_15m.iloc[: i + 1]

        try:
            sigs = adapter.generate_signals("BTCUSDT", bar_df)
        except Exception:
            sigs = []

        regime = selector.get_regime("BTCUSDT")
        regimes[regime] += 1

        month_key = ts.strftime("%Y-%m")
        if month_key not in monthly:
            monthly[month_key] = {"bars": 0, "signals": 0, "regimes": Counter()}
        monthly[month_key]["bars"] += 1
        monthly[month_key]["regimes"][regime] += 1

        if sigs:
            regime_with_signal[regime] += 1
            monthly[month_key]["signals"] += 1
            signals_per_month[month_key] += 1

    print("\n=== Regime Distribution (全年) ===")
    total = sum(regimes.values())
    for r, cnt in sorted(regimes.items(), key=lambda x: -x[1]):
        print(f"  {r}: {cnt} ({100*cnt/total:.1f}%)")

    print("\n=== Regime with Signals ===")
    for r, cnt in sorted(regime_with_signal.items(), key=lambda x: -x[1]):
        print(f"  {r}: {cnt}")

    print("\n=== 每月信号数 ===")
    for month in sorted(monthly.keys()):
        d = monthly[month]
        dominant = d["regimes"].most_common(1)[0]
        print(f"  {month}: signals={d['signals']:3d}  bars={d['bars']:5d}  dominant_regime={dominant[0]} ({dominant[1]} bars)")

    print(f"\nTotal signals: {sum(signals_per_month.values())}")


if __name__ == "__main__":
    main()
