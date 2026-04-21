"""Backtest runner with debug output."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


@dataclass
class Signal:
    qty: Decimal
    side: str
    entry_atr: float | None = None


class EMACrossoverStrategy:
    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._in_position: dict[str, bool] = {}

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
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
            return [Signal(qty=Decimal("1"), side="buy")]
        if in_pos and crossover_down:
            self._in_position[symbol] = False
            return [Signal(qty=Decimal("1"), side="sell")]
        return []


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
    result = engine.run(
        strategy=strategy,
        symbols=["BTCUSDT"],
        start_time=datetime(2025, 1, 1),
        end_time=datetime(2026, 1, 1),
    )
    return result


if __name__ == "__main__":
    result = run()

    print("=" * 60)
    print("BACKTEST REPORT — BTCUSDT 1h — 2025")
    print("Strategy: EMA(20)×EMA(50) Crossover")
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
        price = t.get("entry_price") or t.get("exit_price")
        print(
            f"    {str(t['timestamp'])[:19]}  "
            f"{t['side'].upper():4s}  "
            f"qty={t['qty']:.6f}  "
            f"price=${float(price):.2f}  "
            f"fee=${float(t['fee']):.4f}  "
            f"pnl={pnl_str}"
        )
