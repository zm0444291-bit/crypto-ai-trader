#!/usr/bin/env python3
"""
add_trade.py — 交互式添加交易记录（入场）
比 log_trade.py 更友好的交互式界面

用法：python scripts/add_trade.py
"""

import csv
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.csv"
FIELDNAMES = [
    "id", "symbol", "date", "time", "dir", "entry_price", "stop_loss",
    "take_profit", "exit_price", "pnl_pct", "pnl_abs", "status",
    "strategy", "regime", "atr_pct", "risk_pct", "confidence",
    "idea", "plan_entry", "plan_sl", "plan_tp",
    "execution_notes", "reflection", "optimization",
]


def next_id() -> str:
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


def ask(prompt: str, default: str = "") -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def ask_float(prompt: str, default: float = 0.0) -> float:
    val = input(f"{prompt} [{default}]: ").strip()
    return float(val) if val else default


def ask_int(prompt: str, default: int = 0) -> int:
    val = input(f"{prompt} [{default}]: ").strip()
    return int(val) if val else default


def main() -> None:
    print("=" * 60)
    print("  交易日记 — 记录新交易")
    print("=" * 60)
    print()

    trade_id = next_id()
    symbol = ask("品种", "XAUUSD")
    direction = ask("方向 (LONG/SELL)", "LONG")
    date = ask("日期", datetime.now().strftime("%Y-%m-%d"))
    time = ask("时间", datetime.now().strftime("%H:%M"))
    entry = ask_float("入场价", 0.0)
    sl = ask_float("止损价", 0.0)
    tp = ask_float("止盈价", 0.0)
    risk = ask_float("风险比例 (%)", 2.0)
    strategy = ask("策略", "")
    regime = ask("市场状态 (BULL_TREND/BEAR_TREND/RANGE_BOUND/VOLATILE)", "")
    confidence = ask_float("信号置信度 (0-1)", 0.5)
    atr_pct = ask_float("ATR占总资金比例 (%)", 0.0)
    print()

    print("  --- 交易计划 ---")
    idea = ask("交易想法（为什么做这笔交易）")
    plan_entry = ask("计划入场点")
    plan_sl = ask("计划止损点", str(sl) if sl else "")
    plan_tp = ask("计划止盈点", str(tp) if tp else "")

    trade = {
        "id": trade_id,
        "symbol": symbol,
        "date": date,
        "time": time,
        "dir": direction,
        "entry_price": str(entry),
        "stop_loss": str(sl),
        "take_profit": str(tp),
        "exit_price": "",
        "pnl_pct": "",
        "pnl_abs": "",
        "status": "OPEN",
        "strategy": strategy,
        "regime": regime,
        "atr_pct": str(atr_pct),
        "risk_pct": str(risk),
        "confidence": str(confidence),
        "idea": idea,
        "plan_entry": plan_entry,
        "plan_sl": plan_sl,
        "plan_tp": plan_tp,
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

    print()
    print("=" * 60)
    print(f"  [OK] 已记录 {trade_id}")
    print(f"  {symbol} {direction} @ {entry}")
    print(f"  SL={sl} TP={tp} Risk={risk}%")
    if idea:
        print(f"  想法: {idea[:60]}")
    print("=" * 60)
    print()
    print(f"出场时运行: python scripts/log_trade.py close {trade_id} <exit_price> <pnl_pct> <pnl_abs>")


if __name__ == "__main__":
    main()
