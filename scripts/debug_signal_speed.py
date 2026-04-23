"""Debug which part is slow in the backtest adapter."""
import sys
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_regression_backtest import BacktestAdapter, FeatureCache
from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector

if __name__ == "__main__":
    store = ParquetCandleStore(Path("backtest_data/candles"))
    df = store.load("BTCUSDT", "15m")
    df = df[
        (df["timestamp"] >= pd.Timestamp("2025-01-01", tz="UTC"))
        & (df["timestamp"] <= pd.Timestamp("2025-01-31", tz="UTC"))
    ].copy()
    print(f"Rows: {len(df)}")

    print("Building cache...", flush=True)
    t0 = time.time()
    cache = FeatureCache(df, symbol="BTCUSDT")
    print(f"Cache built in {time.time()-t0:.1f}s")

    selector = StrategySelector()
    adapter = BacktestAdapter(cache, selector)

    # Time just the get() calls
    print("\nTiming get() + select_candidate() for 100 random bars...")
    import random
    sample_ts = random.sample(cache.ts_list[60:], min(100, len(cache.ts_list) - 60))

    t0 = time.time()
    for ts in sample_ts:
        f15m, f1h, f4h = cache.get(ts, n_15m=60)
        candidate = selector.select_candidate(
            symbol="BTCUSDT",
            features_15m=f15m,
            features_1h=f1h,
            features_4h=f4h,
            now=ts,
        )
    elapsed = time.time() - t0
    print(f"100 get()+select_candidate() calls: {elapsed:.2f}s ({elapsed*35:.0f}s projected for 3500 calls)")

    # Time the full engine run
    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10000"),
        interval="15m",
    )
    engine = BacktestEngine(config, store)

    # Monkey-patch generate_signals to time it
    original_gen = adapter.generate_signals
    gen_times: list = []

    def timed_gen(symbol: str, df: pd.DataFrame):
        t0 = time.time()
        result = original_gen(symbol, df)
        gen_times.append(time.time() - t0)
        return result

    adapter.generate_signals = timed_gen

    print("\nRunning backtest...", flush=True)
    t0 = time.time()
    result = engine.run(
        strategy=adapter,
        symbols=["BTCUSDT"],
        start_time=pd.Timestamp("2025-01-01", tz="UTC").to_pydatetime(),
        end_time=pd.Timestamp("2025-01-31", tz="UTC").to_pydatetime(),
    )
    elapsed = time.time() - t0
    print(f"\nFull backtest: {elapsed:.1f}s")
    print(f"generate_signals calls: {len(gen_times)}")
    print(f"Avg time per call: {sum(gen_times)/len(gen_times)*1000:.1f}ms")
    print(f"Max time per call: {max(gen_times)*1000:.1f}ms")
    print(f"Total time in gen: {sum(gen_times):.1f}s")
    print(f"Total trades: {result.total_trades}")
