"""Time the full backtest with 1 week of data."""
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
        (df["timestamp"] >= pd.Timestamp("2025-07-01", tz="UTC"))
        & (df["timestamp"] <= pd.Timestamp("2025-07-08", tz="UTC"))
    ].copy()
    print(f"Rows: {len(df)}")

    t0 = time.time()
    cache = FeatureCache(df, symbol="BTCUSDT")
    print(f"Cache: {time.time()-t0:.1f}s")

    selector = StrategySelector()
    adapter = BacktestAdapter(cache, selector)

    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10000"),
        interval="15m",
    )
    engine = BacktestEngine(config, store)

    t0 = time.time()
    result = engine.run(
        strategy=adapter,
        symbols=["BTCUSDT"],
        start_time=pd.Timestamp("2025-07-01", tz="UTC").to_pydatetime(),
        end_time=pd.Timestamp("2025-07-08", tz="UTC").to_pydatetime(),
    )
    print(f"engine.run: {time.time()-t0:.1f}s")
    print(f"Trades: {result.total_trades}")
