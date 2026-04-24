#!/usr/bin/env python3
"""
log_trade.py — 记录一笔新交易到 trade_journal.csv
用法：python scripts/log_trade.py --symbol XAUUSD --direction LONG \
    --entry 2345.5 --sl 2335.0 --tp 2370.0 --risk 2.0 \
    --strategy "BB(5,0.5)" --regime "BULL_TREND" --confidence 0.75 \
    --idea "布林带收窄后向上突破，ADR显示今日波动幅度充足" \
    --plan_entry "价格回踩2350入场" --plan_sl "2335" --plan_tp "2370"
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.csv"

# CSV 列顺序（与 trade_journal.csv header 一致）
FIELDNAMES = [
    "id", "symbol", "date", "time", "dir", "entry_price", "stop_loss",
    "take_profit", "exit_price", "pnl_pct", "pnl_abs", "status",
    "strategy", "regime", "atr_pct", "risk_pct", "confidence",
    "idea", "plan_entry", "plan_sl", "plan_tp",
    "execution_notes", "reflection", "optimization",
]


def next_id() -> str:
    """生成下一个交易ID：T-001, T-002, ..."""
    if not JOURNAL_PATH.exists():
        return "T-001"
    max_id = 0
    with JOURNAL_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                nid = int(row["id"].split("-")[1])
                if nid > max_id:
                    max_id = nid
            except (ValueError, IndexError):
                pass
    return f"T-{max_id + 1:03d}"


def log_trade(args: argparse.Namespace) -> None:
    now = datetime.now()
    trade = {
        "id": next_id(),
        "symbol": args.symbol,
        "date": args.date or now.strftime("%Y-%m-%d"),
        "time": args.time or now.strftime("%H:%M"),
        "dir": args.direction,
        "entry_price": args.entry,
        "stop_loss": args.sl,
        "take_profit": args.tp,
        "exit_price": "",
        "pnl_pct": "",
        "pnl_abs": "",
        "status": "OPEN",  # OPEN / WIN / LOSS / BREAKEVEN
        "strategy": args.strategy,
        "regime": args.regime,
        "atr_pct": args.atr_pct or "",
        "risk_pct": args.risk,
        "confidence": args.confidence or "",
        "idea": args.idea or "",
        "plan_entry": args.plan_entry or "",
        "plan_sl": str(args.sl) if args.sl else "",
        "plan_tp": str(args.tp) if args.tp else "",
        "execution_notes": "",
        "reflection": "",
        "optimization": "TBD",
    }

    file_exists = JOURNAL_PATH.exists()
    with JOURNAL_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)

    print(f"[OK] 记录 {trade['id']} {trade['symbol']} {trade['dir']} @ {trade['entry_price']} (status=OPEN)")
    print(f"     SL={trade['stop_loss']} TP={trade['take_profit']} Risk={trade['risk_pct']}%")


def close_trade(trade_id: str, exit_price: float, pnl_pct: float, pnl_abs: float,
                 execution_notes: str = "", reflection: str = "", optimization: str = "TBD") -> None:
    """更新交易记录（出场）"""
    if not JOURNAL_PATH.exists():
        print("[ERROR] trade_journal.csv not found")
        sys.exit(1)

    rows: list[dict[str, str]] = []
    with JOURNAL_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["id"] == trade_id:
                row["exit_price"] = str(exit_price)
                row["pnl_pct"] = str(pnl_pct)
                row["pnl_abs"] = str(pnl_abs)
                row["status"] = "WIN" if pnl_pct > 0 else "LOSS" if pnl_pct < 0 else "BREAKEVEN"
                row["execution_notes"] = execution_notes
                row["reflection"] = reflection
                row["optimization"] = optimization
            rows.append(row)

    with JOURNAL_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[OK] 更新 {trade_id} → status={row['status']} P&L={pnl_pct:+.3f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="记录交易到 trade_journal.csv")
    sub = parser.add_subparsers(dest="cmd")

    # log subcommand
    p_log = sub.add_parser("log", help="记录新交易")
    p_log.add_argument("--symbol", required=True, help="品种，如 XAUUSD")
    p_log.add_argument("--direction", required=True, choices=["LONG", "SELL"], help="方向")
    p_log.add_argument("--entry", type=float, required=True, help="入场价")
    p_log.add_argument("--sl", type=float, required=True, help="止损价")
    p_log.add_argument("--tp", type=float, required=True, help="止盈价")
    p_log.add_argument("--risk", type=float, default=2.0, help="风险比例 %% (default: 2.0)")
    p_log.add_argument("--strategy", default="", help="策略名")
    p_log.add_argument("--regime", default="", help="市场状态")
    p_log.add_argument("--confidence", type=float, default=0.0, help="信号置信度 0-1")
    p_log.add_argument("--atr-pct", type=float, default=0.0, help="ATR占总资金比例 %%")
    p_log.add_argument("--idea", default="", help="交易想法")
    p_log.add_argument("--plan-entry", dest="plan_entry", default="", help="计划入场点")
    p_log.add_argument("--plan-sl", dest="plan_sl", default="", help="计划止损")
    p_log.add_argument("--plan-tp", dest="plan_tp", default="", help="计划止盈")
    p_log.add_argument("--date", default="", help="交易日期 YYYY-MM-DD (default: today)")
    p_log.add_argument("--time", default="", help="交易时间 HH:MM (default: now)")

    # close subcommand
    p_close = sub.add_parser("close", help="更新交易出场")
    p_close.add_argument("trade_id", help="交易ID，如 T-001")
    p_close.add_argument("exit_price", type=float, help="出场价")
    p_close.add_argument("pnl_pct", type=float, help="盈亏比例 %%")
    p_close.add_argument("pnl_abs", type=float, help="盈亏金额")
    p_close.add_argument("--notes", default="", help="执行备注")
    p_close.add_argument("--reflection", default="", help="反思")
    p_close.add_argument("--optimization", default="TBD", help="优化建议")

    args = parser.parse_args()

    if args.cmd == "log":
        log_trade(args)
    elif args.cmd == "close":
        close_trade(args.trade_id, args.exit_price, args.pnl_pct, args.pnl_abs,
                    args.notes, args.reflection, args.optimization)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
