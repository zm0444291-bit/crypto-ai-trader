"""Debug script to identify why backtest produces 0 trades."""
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


class EMACrossoverStrategy:
    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._in_position: dict[str, bool] = {}

    def generate_signals(self, symbol: str, df: pd.DataFrame):
        if len(df) < self.slow_period + 2:
            return []
        closes = df["close"].astype(float)
        fast = closes.ewm(span=self.fast_period, adjust=False).mean()
        slow = closes.ewm(span=self.slow_period, adjust=False).mean()
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
            return [SimpleSignal(qty=Decimal("1"), side="buy")]
        if in_pos and crossover_down:
            self._in_position[symbol] = False
            return [SimpleSignal(qty=Decimal("1"), side="sell")]
        return []


class SimpleSignal:
    qty: Decimal
    side: str
    entry_atr: float | None = None
    def __init__(self, qty, side, entry_atr=None):
        self.qty = qty
        self.side = side
        self.entry_atr = entry_atr


def run():
    store = ParquetCandleStore(Path("backtest_data/candles"))
    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10_000"),
        interval="1h",
    )
    engine = BacktestEngine(config, store)
    strategy = EMACrossoverStrategy(fast_period=20, slow_period=50)
    
    # Load data directly to check
    df = store.load("BTCUSDT", "1h")
    _start = datetime(2025, 1, 1, tzinfo=UTC)
    _end = datetime(2026, 1, 1, tzinfo=UTC)
    df2025 = df[(df["timestamp"] >= _start) & (df["timestamp"] <= _end)].reset_index(drop=True)
    print(f"Data rows for 2025: {len(df2025)}")
    print(f"Range: {df2025['timestamp'].min()} to {df2025['timestamp'].max()}")
    
    # Test signal at first valid bar
    first_valid_i = 52  # slow_period + 2
    df_test = df2025[df2025["timestamp"] <= df2025.iloc[first_valid_i]["timestamp"]]
    sigs = list(strategy.generate_signals("BTCUSDT", df_test))
    print(f"Signals at first valid bar: {sigs}")
    
    # Count signals across entire timeline
    all_ts = sorted(df2025["timestamp"].tolist())
    strategy2 = EMACrossoverStrategy(fast_period=20, slow_period=50)
    buy_count = 0
    sell_count = 0
    for ts in all_ts:
        df_t = df2025[df2025["timestamp"] <= ts]
        sigs = list(strategy2.generate_signals("BTCUSDT", df_t))
        for s in sigs:
            if s.side == "buy":
                buy_count += 1
            else:
                sell_count += 1
    print(f"Total buy signals (strategy): {buy_count}")
    print(f"Total sell signals (strategy): {sell_count}")
    
    # Run engine
    result = engine.run(
        strategy=strategy,
        symbols=["BTCUSDT"],
        start_time=datetime(2025, 1, 1),
        end_time=datetime(2026, 1, 1),
    )
    print(f"\nEngine result trades: {result.total_trades}")
    return result


if __name__ == "__main__":
    result = run()
    print("\n=== REPORT ===")
    print(f"  Total Trades   : {result.total_trades}")
    print(f"  Initial Equity : ${result.initial_equity:,.2f}")
    print(f"  Final Equity   : ${result.final_equity:,.2f}")
