"""Debug: patch engine to catch swallowed exceptions and count signals precisely."""
import sys
import traceback
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_regression_backtest import BacktestAdapter, FeatureCache, Signal
from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector


class VerboseAdapter(BacktestAdapter):
    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        try:
            result = super().generate_signals(symbol, df)
            if result:
                print(f"  SIGNAL at {self._bars['timestamp'].iloc[-1]}: {result[0].side} {result[0].qty}")
            return result
        except Exception as e:
            print(f"  EXCEPTION in generate_signals: {e}")
            traceback.print_exc()
            return []


if __name__ == "__main__":
    store = ParquetCandleStore(Path("backtest_data/candles"))
    df = store.load("BTCUSDT", "15m")
    df = df[
        (df["timestamp"] >= pd.Timestamp("2025-09-25", tz="UTC"))
        & (df["timestamp"] <= pd.Timestamp("2025-10-10", tz="UTC"))
    ].copy()
    print(f"Rows: {len(df)}")

    cache = FeatureCache(df, symbol="BTCUSDT")
    selector = StrategySelector()
    adapter = VerboseAdapter(cache, selector)

    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10000"),
        interval="15m",
    )
    engine = BacktestEngine(config, store)

    result = engine.run(
        strategy=adapter,
        symbols=["BTCUSDT"],
        start_time=pd.Timestamp("2025-09-25", tz="UTC").to_pydatetime(),
        end_time=pd.Timestamp("2025-10-10", tz="UTC").to_pydatetime(),
    )

    print(f"\nTotal trades: {result.total_trades}")
