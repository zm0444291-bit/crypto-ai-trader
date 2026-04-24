"""Debug: find why 0 trades — print all candidate signals."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_regression_backtest import FeatureCache
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector

if __name__ == "__main__":
    store = ParquetCandleStore(Path("backtest_data/candles"))
    df = store.load("BTCUSDT", "15m")
    df = df[
        (df["timestamp"] >= pd.Timestamp("2025-07-01", tz="UTC"))
        & (df["timestamp"] <= pd.Timestamp("2025-12-31", tz="UTC"))
    ].copy()

    cache = FeatureCache(df, symbol="BTCUSDT")
    selector = StrategySelector()

    # Sample every 10 bars from the second half of the year
    mid = len(cache.ts_list) // 2
    signals = []
    for i in range(mid, len(cache.ts_list), 10):
        ts = cache.ts_list[i]
        f15m, f1h, f4h = cache.get(ts, n_15m=60)
        if len(f15m) < 60:
            continue
        c = selector.select_candidate(
            symbol="BTCUSDT",
            features_15m=f15m,
            features_1h=f1h,
            features_4h=f4h,
            now=ts,
        )
        if c:
            signals.append((ts, c))

    print(f"Signals in ~3000 bars: {len(signals)}")
    for ts, c in signals[:10]:
        print(f"  {ts}  {c.strategy_name}  {c.side}  atr={c.entry_reference}")
