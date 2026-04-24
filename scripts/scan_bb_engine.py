#!/usr/bin/env python3
"""系统化扫描BB策略在真实引擎中的表现 — 找3年全盈利的参数组合"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.backtest.engine import BacktestEngine, BacktestConfig
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.bollinger_band import BollingerBandStrategy


store = ParquetCandleStore(Path("backtest_data/candles"))

# Grid: bb_period x bb_std x fast_sma x slow_sma
# Focus on combinations with good trade frequency
configs = []
for bb_p in [5, 7, 10, 14, 20, 30]:
    for bb_s in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        for f_sma, s_sma in [(5,10),(5,20),(7,20),(10,20),(10,30),(10,50),(14,30),(20,50),(20,80)]:
            if f_sma >= s_sma:
                continue
            configs.append((bb_p, bb_s, f_sma, s_sma))

print(f"Testing {len(configs)} parameter combinations...")

SYMBOLS = ["xauusd", "eurusd", "gbpusd"]
YEARS = [2023, 2024, 2025]

qualified = []

for idx, (bb_p, bb_s, f_sma, s_sma) in enumerate(configs):
    if (idx + 1) % 200 == 0:
        print(f"  [{idx+1}/{len(configs)}]")

    for sym in SYMBOLS:
        results = {}
        for year in YEARS:
            strat = BollingerBandStrategy(
                bb_period=bb_p, bb_std=bb_s,
                fast_sma_period=f_sma, slow_sma_period=s_sma,
            )
            config = BacktestConfig(
                initial_equity=Decimal("10000"),
                fee_bps=Decimal("1"),
                interval="1d",
            )
            engine = BacktestEngine(config=config, store=store)
            try:
                result = engine.run(
                    strategy=strat,
                    symbols=[sym],
                    start_time=datetime(year, 1, 1, tzinfo=timezone.utc),
                    end_time=datetime(year, 12, 31, tzinfo=timezone.utc),
                )
                ret = float(result.total_return_pct)
                trades = result.total_trades
                results[year] = (ret, trades)
            except Exception:
                results[year] = (None, 0)

        # Check: all 3 years profitable?
        all_profitable = all(
            results[y][0] is not None and results[y][0] > 0
            for y in YEARS
        )
        avg_trades = sum(results[y][1] for y in YEARS) / 3

        if all_profitable and avg_trades >= 10:
            total_ret = sum(results[y][0] for y in YEARS)
            qualified.append({
                "sym": sym,
                "bb_p": bb_p, "bb_s": bb_s,
                "f_sma": f_sma, "s_sma": s_sma,
                "ret_2023": results[2023][0],
                "ret_2024": results[2024][0],
                "ret_2025": results[2025][0],
                "trades_2023": results[2023][1],
                "trades_2024": results[2024][1],
                "trades_2025": results[2025][1],
                "total_ret": total_ret,
                "avg_trades": avg_trades,
            })

qualified.sort(key=lambda x: x["total_ret"], reverse=True)

print(f"\n{'='*100}")
print(f"{'Sym':<8} {'BB(p,s)':<12} {'SMA(f,s)':<14} {'2023':>7} {'2024':>7} {'2025':>7} {'3yr':>7} {'AvgTrd':>8}")
print(f"{'='*100}")
for q in qualified[:50]:
    print(
        f"{q['sym']:<8} "
        f"({q['bb_p']},{q['bb_s']})    "
        f"({q['f_sma']},{q['s_sma']})    "
        f"{q['ret_2023']:>+6.1f}% {q['ret_2024']:>+6.1f}% {q['ret_2025']:>+6.1f}% "
        f"{q['total_ret']:>+6.1f}% {q['avg_trades']:>8.0f} "
        f"({q['trades_2023']}/{q['trades_2024']}/{q['trades_2025']})"
    )

print(f"\nTotal qualifying combos: {len(qualified)}")
