"""Debug: trace through the engine's run loop."""
import sys
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore

store = ParquetCandleStore(Path('backtest_data/candles'))
config = BacktestConfig(
    fee_bps=Decimal("10"),
    slippages={"default": Decimal("5")},
    initial_equity=Decimal("10_000"),
    interval="1h",
)
engine = BacktestEngine(config, store)

# Patch engine to add debug output
orig_run = engine.run

class EMACrossoverStrategy:
    def __init__(self):
        self._in_position = {}
        self.call_count = 0
        self.signal_count = 0

    def generate_signals(self, symbol, df):
        self.call_count += 1
        if len(df) < 52:
            return []
        closes = df["close"].astype(float)
        fast = closes.ewm(span=20, adjust=False).mean()
        slow = closes.ewm(span=50, adjust=False).mean()
        fast_vals = fast.values
        slow_vals = slow.values
        in_pos = self._in_position.get(symbol, False)
        crossover_up = (
            fast_vals[-2] <= slow_vals[-2] and fast_vals[-1] > slow_vals[-1]
        )
        crossover_down = (
            fast_vals[-2] >= slow_vals[-2] and fast_vals[-1] < slow_vals[-1]
        )
        if not in_pos and crossover_up:
            self._in_position[symbol] = True
            self.signal_count += 1
            print(f"  [SIGNAL] BUY at {df['timestamp'].iloc[-1]}")
            return [__import__('dataclasses').dataclass(__import__('typing').Annotated)[__import__('typing').Any](qty=Decimal("1"), side="buy")]
        if in_pos and crossover_down:
            self._in_position[symbol] = False
            self.signal_count += 1
            print(f"  [SIGNAL] SELL at {df['timestamp'].iloc[-1]}")
            return [__import__('dataclasses').dataclass(__import__('typing').Annotated)[__import__('typing').Any](qty=Decimal("1"), side="sell")]
        return []

strategy = EMACrossoverStrategy()

result = engine.run(
    strategy=strategy,
    symbols=["BTCUSDT"],
    start_time=datetime(2025, 1, 1),
    end_time=datetime(2026, 1, 1),
)

print(f"\nTotal generate_signals calls: {strategy.call_count}")
print(f"Total signals generated: {strategy.signal_count}")
print(f"Total trades: {result.total_trades}")
