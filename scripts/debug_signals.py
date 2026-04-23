#!/usr/bin/env python3
"""在 engine.run 内联执行路径上加详细日志"""
import sys

sys.path.insert(0, ".")

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from scripts.run_regression_backtest import BacktestAdapter, FeatureCache
from trading.backtest.engine import BacktestConfig, BacktestEngine, PortfolioAccount, Position
from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector


def run():
    store = ParquetCandleStore(Path("backtest_data/candles"))

    # Q4 测试区间
    start = datetime(2025, 9, 1, tzinfo=UTC)
    end = datetime(2025, 10, 31, tzinfo=UTC)

    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10_000"),
        risk_per_trade_pct=Decimal("2"),
        interval="15m",
    )

    # 只加载 15m 数据
    df_15m = store.load("BTCUSDT", "15m")
    df_15m = df_15m[(df_15m["timestamp"] >= start) & (df_15m["timestamp"] <= end)].copy()

    print(f"Loaded {len(df_15m)} candles (Sep-Oct 2025)")

    cache = FeatureCache(df_15m, symbol="BTCUSDT")
    selector = StrategySelector()
    adapter = BacktestAdapter(cache, selector)

    # 重建 engine 的完整运行逻辑，但加日志
    _start_utc = start
    _end_utc = end
    data = {"BTCUSDT": df_15m}

    all_ts = set()
    for _df in data.values():
        all_ts.update(_df["timestamp"].tolist())
    timeline = sorted(all_ts)
    print(f"Timeline: {len(timeline)} bars, from {timeline[0]} to {timeline[-1]}")

    portfolio = PortfolioAccount(cash_balance=config.initial_equity)
    positions = {}
    trades = []


    signal_count = 0
    skip_log = []

    for _i, ts in enumerate(timeline):
        sym = "BTCUSDT"
        sym_df = data[sym]
        idx_list = sym_df.index[sym_df["timestamp"] == ts].tolist()
        if not idx_list:
            continue
        idx = idx_list[0]

        bars_up_to_t = sym_df[sym_df["timestamp"] <= ts]
        try:
            signals = adapter.generate_signals(sym, bars_up_to_t)
        except Exception as e:
            print(f"  EXCEPTION at {ts}: {e}")
            signals = []

        for sig in signals:
            signal_count += 1
            pos = positions.get(sym)
            slip = config.slippages.get("default", Decimal("0"))

            if sig.side == "buy" and pos is None:
                next_idx = idx + 1
                if next_idx >= len(sym_df):
                    skip_log.append({
                        "signal_n": signal_count,
                        "ts": ts,
                        "idx": idx,
                        "len_df": len(sym_df),
                        "next_idx": next_idx,
                        "reason": "no_next_bar"
                    })
                    continue

                notional = portfolio.cash_balance * Decimal("0.95")
                if notional <= Decimal("0"):
                    skip_log.append({
                        "signal_n": signal_count,
                        "ts": ts,
                        "idx": idx,
                        "notional": notional,
                        "reason": "no_cash"
                    })
                    continue

                next_open = Decimal(str(sym_df.iloc[next_idx]["open"]))
                entry_price = next_open * (Decimal("1") + slip / Decimal("10000"))
                fee_bps = config.fee_bps
                qty = notional / entry_price
                fee = entry_price * qty * fee_bps / Decimal("10000")
                cost = entry_price * qty + fee

                portfolio.cash_balance -= cost
                positions[sym] = Position(
                    symbol=sym,
                    qty=qty,
                    avg_entry_price=entry_price,
                    fees_paid_usdt=fee,
                    opened_at=ts,
                    entry_atr=getattr(sig, "entry_atr", None),
                )
                trades.append({
                    "symbol": sym,
                    "side": "buy",
                    "entry_price": entry_price,
                    "qty": qty,
                    "entry_ts": ts,
                    "next_open": next_open,
                })

    print(f"\nTotal signals: {signal_count}")
    print(f"Total trades executed: {len(trades)}")
    print("Skip reasons:")
    from collections import Counter
    reasons = Counter(s["reason"] for s in skip_log)
    for reason, count in reasons.items():
        print(f"  {reason}: {count}")

    if skip_log:
        print("\nFirst 5 skips:")
        for s in skip_log[:5]:
            print(f"  {s}")

    print("\nFirst 5 trades:")
    for t in trades[:5]:
        print(f"  {t}")

    # 现在用真实 engine 跑一次对比
    print("\n--- Running actual engine.run for comparison ---")
    engine = BacktestEngine(config, store)
    result = engine.run(adapter, ["BTCUSDT"], start, end)
    print(f"Engine total_trades: {result.total_trades}")


if __name__ == "__main__":
    run()
