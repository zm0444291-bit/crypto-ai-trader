#!/usr/bin/env python3
"""Verify BB strategy in the real project engine using engine.run()."""
from __future__ import annotations
import sys, pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.backtest.engine import BacktestEngine, BacktestConfig
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.bollinger_band import BollingerBandStrategy


store = ParquetCandleStore(Path("backtest_data/candles"))

configs = [
    # (symbol, interval, start_year, end_year, period, std)
    ("xauusd", "1d", 2023, 2023, 5, 1.0),
    ("xauusd", "1d", 2024, 2024, 5, 1.0),
    ("xauusd", "1d", 2025, 2025, 5, 1.0),
    ("eurusd", "1d", 2023, 2023, 5, 1.0),
    ("eurusd", "1d", 2024, 2024, 5, 1.0),
    ("eurusd", "1d", 2025, 2025, 5, 1.0),
    ("gbpusd", "1d", 2023, 2023, 5, 1.0),
    ("gbpusd", "1d", 2024, 2024, 5, 1.0),
    ("gbpusd", "1d", 2025, 2025, 5, 1.0),
    ("xauusd", "1d", 2023, 2023, 7, 1.0),
    ("xauusd", "1d", 2024, 2024, 7, 1.0),
    ("xauusd", "1d", 2025, 2025, 7, 1.0),
    ("xauusd", "1d", 2023, 2023, 10, 1.0),
    ("xauusd", "1d", 2024, 2024, 10, 1.0),
    ("xauusd", "1d", 2025, 2025, 10, 1.0),
]

print(f"{'Symbol':<8} {'Int':<4} {'Period':<7} {'Year':<5} {'Ret%':>8} {'Sharpe':>8} {'MaxDD%':>8} {'Trades':>7} {'Win%':>6}")
print("=" * 70)

for sym, interval, sy, ey, period, std in configs:
    strat = BollingerBandStrategy(bb_period=period, bb_std=std)
    config = BacktestConfig(
        initial_equity=Decimal("10000"),
        fee_bps=Decimal("1"),
        slippages={"default": Decimal("0")},
        interval=interval,
    )
    engine = BacktestEngine(config=config, store=store)

    start = datetime(sy, 1, 1, tzinfo=timezone.utc)
    end = datetime(ey, 12, 31, tzinfo=timezone.utc)

    try:
        result = engine.run(
            strategy=strat,
            symbols=[sym],
            start_time=start,
            end_time=end,
        )
        ret = float(result.total_return_pct)
        sharpe = result.sharpe_ratio
        max_dd = float(result.max_drawdown_pct)
        trades = result.total_trades
        win_rate = float(result.win_rate) * 100
        print(f"{sym:<8} {interval:<4} {period:<7} {sy:<5} {ret:>+8.1f}% {sharpe:>+8.2f} {max_dd:>8.1f}% {trades:>7} {win_rate:>6.0f}%")
    except Exception as e:
        print(f"{sym:<8} {interval:<4} {period:<7} {sy:<5} ERROR: {e}")

print()
print("Done.")
