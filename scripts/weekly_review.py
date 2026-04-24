#!/usr/bin/env python3
"""
weekly_review.py — 每周复盘 + 策略自动迭代
自动分析上周交易，生成优化建议，并可选择将改进写入策略代码

用法：
    python scripts/weekly_review.py                    # 分析并输出报告
    python scripts/weekly_review.py --auto-tune        # 分析 + 自动调参
    python scripts/weekly_review.py --write-changes    # 分析 + 写入策略改动
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.csv"
BACKTEST_DATA = Path(__file__).parent.parent / "backtest_data" / "candles"


@dataclass
class Trade:
    id: str
    symbol: str
    date: str
    time: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    status: str
    strategy: str
    regime: str
    atr_pct: float
    risk_pct: float
    confidence: float
    idea: str
    plan_entry: str
    plan_sl: str
    plan_tp: str
    execution_notes: str
    reflection: str
    optimization: str


@dataclass
class WeekStats:
    start_date: str
    end_date: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    best_trade: Trade | None
    worst_trade: Trade | None
    by_strategy: dict[str, dict]
    by_symbol: dict[str, dict]
    by_regime: dict[str, dict]
    execution_issues: list[Trade]
    common_reflections: list[str]


def load_trades(path: Path) -> list[Trade]:
    trades: list[Trade] = []
    if not path.exists():
        return trades
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("id") or row.get("status") == "OPEN":
                continue
            trades.append(
                Trade(
                    id=row["id"].strip(),
                    symbol=row["symbol"].strip(),
                    date=row["date"].strip(),
                    time=row["time"].strip(),
                    direction=row["dir"].strip(),
                    entry_price=float(row["entry_price"]) if row["entry_price"] else 0.0,
                    stop_loss=float(row["stop_loss"]) if row["stop_loss"] else 0.0,
                    take_profit=float(row["take_profit"]) if row["take_profit"] else 0.0,
                    exit_price=float(row["exit_price"]) if row["exit_price"] else 0.0,
                    pnl_pct=float(row["pnl_pct"]) if row["pnl_pct"] else 0.0,
                    pnl_abs=float(row["pnl_abs"]) if row["pnl_abs"] else 0.0,
                    status=row["status"].strip().upper(),
                    strategy=row["strategy"].strip(),
                    regime=row["regime"].strip(),
                    atr_pct=float(row["atr_pct"]) if row["atr_pct"] else 0.0,
                    risk_pct=float(row["risk_pct"]) if row["risk_pct"] else 0.0,
                    confidence=float(row["confidence"]) if row["confidence"] else 0.0,
                    idea=row["idea"].strip(),
                    plan_entry=row["plan_entry"].strip(),
                    plan_sl=row["plan_sl"].strip(),
                    plan_tp=row["plan_tp"].strip(),
                    execution_notes=row["execution_notes"].strip(),
                    reflection=row["reflection"].strip(),
                    optimization=row["optimization"].strip(),
                )
            )
    return trades


def trades_this_week(trades: list[Trade], week_offset: int = 0) -> list[Trade]:
    today = datetime.now()
    days_ago = week_offset * 7
    week_start = today - timedelta(days=today.weekday() + days_ago)
    week_end = week_start + timedelta(days=6)
    start_str = week_start.strftime("%Y-%m-%d")
    end_str = week_end.strftime("%Y-%m-%d")
    return [t for t in trades if start_str <= t.date <= end_str]


def win_rate(t: list[Trade]) -> float:
    return sum(1 for x in t if x.status == "WIN") / len(t) if t else 0.0


def avg_win(t: list[Trade]) -> float:
    w = [x.pnl_pct for x in t if x.status == "WIN"]
    return sum(w) / len(w) if w else 0.0


def avg_loss(t: list[Trade]) -> float:
    losses = [x.pnl_pct for x in t if x.status == "LOSS"]
    return sum(losses) / len(losses) if losses else 0.0


def expectancy(t: list[Trade]) -> float:
    wr = win_rate(t)
    aw = avg_win(t)
    al = avg_loss(t)
    return wr * aw + (1 - wr) * al


def profit_factor(t: list[Trade]) -> float:
    gw = sum(x.pnl_abs for x in t if x.status == "WIN")
    gl = abs(sum(x.pnl_abs for x in t if x.status == "LOSS"))
    return gw / gl if gl else 0.0


def max_drawdown(t: list[Trade]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for x in t:
        equity *= 1 + x.pnl_pct / 100
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100


def group_by(t: list[Trade], key: str) -> dict[str, list[Trade]]:
    groups: dict[str, list[Trade]] = {}
    for x in t:
        if key == "strategy":
            g = x.strategy or "UNKNOWN"
        elif key == "symbol":
            g = x.symbol or "UNKNOWN"
        elif key == "regime":
            g = x.regime or "UNKNOWN"
        elif key == "status":
            g = x.status or "UNKNOWN"
        else:
            g = "UNKNOWN"
        groups.setdefault(g, []).append(x)
    return groups


def stats_for_group(grp: list[Trade]) -> dict:
    return {
        "n": len(grp),
        "win_rate": win_rate(grp),
        "avg_win": avg_win(grp),
        "avg_loss": avg_loss(grp),
        "expectancy": expectancy(grp),
        "profit_factor": profit_factor(grp),
        "max_dd": max_drawdown(grp),
        "total_pnl": sum(x.pnl_pct for x in grp),
    }


def analyze_week(trades: list[Trade], week_offset: int = 0) -> WeekStats:
    week_trades = trades_this_week(trades, week_offset)
    today = datetime.now()
    days_ago = week_offset * 7
    week_start = today - timedelta(days=today.weekday() + days_ago)
    week_end = week_start + timedelta(days=6)
    start_str = week_start.strftime("%Y-%m-%d")
    end_str = week_end.strftime("%Y-%m-%d")

    wins = [t for t in week_trades if t.status == "WIN"]
    losses = [t for t in week_trades if t.status == "LOSS"]
    sorted_trades = sorted(week_trades, key=lambda x: x.pnl_pct, reverse=True)

    by_strategy = {k: stats_for_group(v) for k, v in group_by(week_trades, "strategy").items()}
    by_symbol = {k: stats_for_group(v) for k, v in group_by(week_trades, "symbol").items()}
    by_regime = {k: stats_for_group(v) for k, v in group_by(week_trades, "regime").items()}

    execution_issues = [
        t for t in week_trades
        if t.execution_notes and ("偏离" in t.execution_notes or "未按" in t.execution_notes)
    ]

    # Collect unique reflections
    seen_reflections: set[str] = set()
    common_reflections = []
    for t in week_trades:
        if t.reflection and t.reflection not in seen_reflections:
            seen_reflections.add(t.reflection)
            common_reflections.append(t.reflection[:120])

    return WeekStats(
        start_date=start_str,
        end_date=end_str,
        total_trades=len(week_trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=win_rate(week_trades),
        total_pnl=sum(t.pnl_pct for t in week_trades),
        avg_win=avg_win(week_trades),
        avg_loss=avg_loss(week_trades),
        expectancy=expectancy(week_trades),
        profit_factor=profit_factor(week_trades),
        max_drawdown=max_drawdown(week_trades),
        best_trade=sorted_trades[0] if sorted_trades else None,
        worst_trade=sorted_trades[-1] if sorted_trades else None,
        by_strategy=by_strategy,
        by_symbol=by_symbol,
        by_regime=by_regime,
        execution_issues=execution_issues,
        common_reflections=common_reflections,
    )


def generate_insights(s: WeekStats, all_trades: list[Trade]) -> list[str]:
    insights: list[str] = []

    # Overall assessment
    if s.total_trades == 0:
        insights.append("本周无交易记录。")
        return insights

    if s.win_rate >= 0.6:
        insights.append(f"胜率 {s.win_rate*100:.0f}% 表现良好（目标 >55%）。")
    elif s.win_rate < 0.4:
        insights.append(f"胜率 {s.win_rate*100:.0f}% 偏低，需要检查信号质量。")

    if s.expectancy > 0.3:
        insights.append(f"Expectancy {s.expectancy:.3f}%/笔 优秀（盈亏比健康）。")
    elif s.expectancy < 0.1:
        insights.append(f"Expectancy {s.expectancy:.3f}%/笔 偏低，考虑调整止损/止盈比例。")

    if s.profit_factor >= 1.5:
        insights.append(f"Profit Factor {s.profit_factor:.2f} 优秀（盈 > 亏 1.5倍以上）。")
    elif s.profit_factor < 1.0 and s.total_trades >= 3:
        insights.append(f"Profit Factor {s.profit_factor:.2f} < 1，本周整体亏损。")

    if s.max_drawdown > 3.0:
        insights.append(f"Max Drawdown {s.max_drawdown:.1f}% 偏高（2%风险单笔可能过大）。")

    # Strategy comparison
    if len(s.by_strategy) > 1:
        best_strat = max(s.by_strategy.items(), key=lambda x: x[1]["expectancy"])
        worst_strat = min(
            (x for x in s.by_strategy.items() if x[1]["n"] >= 2),
            key=lambda x: x[1]["expectancy"],
            default=None,
        )
        if best_strat[1]["expectancy"] > 0:
            insights.append(f"最佳策略：{best_strat[0]}（E={best_strat[1]['expectancy']:.3f}%，n={best_strat[1]['n']}）")
        if worst_strat and worst_strat[1]["expectancy"] < 0:
            insights.append(f"最差策略：{worst_strat[0]}（E={worst_strat[1]['expectancy']:.3f}%，n={worst_strat[1]['n']}），考虑暂停或优化")

    # Regime analysis
    if len(s.by_regime) > 1:
        profitable_regimes = [k for k, v in s.by_regime.items() if v["expectancy"] > 0]
        loss_regimes = [k for k, v in s.by_regime.items() if v["expectancy"] < 0 and v["n"] >= 2]
        if profitable_regimes:
            insights.append(f"盈利状态：{', '.join(profitable_regimes)}，在这些状态下可适当增加仓位。")
        if loss_regimes:
            insights.append(f"亏损状态：{', '.join(loss_regimes)}，建议在亏损状态减少交易或空仓。")

    # Execution issues
    if s.execution_issues:
        insights.append(f"执行问题：{len(s.execution_issues)}笔交易存在执行偏差，需加强纪律。")

    # Rolling performance (last 4 weeks)
    recent_weeks = [analyze_week(all_trades, i) for i in range(1, 5)]
    recent_pnls = [w.total_pnl for w in recent_weeks if w.total_trades > 0]
    if len(recent_pnls) >= 2:
        avg_recent = sum(recent_pnls) / len(recent_pnls)
        if s.total_pnl < avg_recent * 0.5 and s.total_pnl < 0:
            insights.append(f"本周表现 ({s.total_pnl:.2f}%) 显著低于近{len(recent_pnls)}周均值 ({avg_recent:.2f}%)，需要复盘原因。")

    return insights


def generate_action_items(s: WeekStats) -> list[str]:
    actions: list[str] = []

    if s.total_trades == 0:
        actions.append("下周目标：至少完成3笔交易，避免过度观望。")
        return actions

    # Win rate check
    if s.win_rate < 0.45 and s.total_trades >= 5:
        actions.append("胜率偏低：提高入场标准，只在 confidence > 0.7 时入场。")

    # Expectancy check
    if s.expectancy < 0.15 and s.total_trades >= 5:
        actions.append("Expectancy偏低：检查止损是否过小（被扫）或止盈是否过远（吃不到）。")

    # PF check
    if s.profit_factor < 1.0 and s.total_trades >= 3:
        actions.append("Profit Factor < 1：本周整体亏损，暂时降低单笔风险至1%，等回测验证后再恢复。")

    # Drawdown check
    if s.max_drawdown > 5.0:
        actions.append(f"MaxDD {s.max_drawdown:.1f}% 过高：下周围绕2%风险操作，不追加仓位。")

    # Execution issues
    if s.execution_issues:
        actions.append("执行纪律问题：下次交易前先写好 plan，入场后不临时改止损/止盈。")

    # Confidence correlation
    if s.total_trades >= 3:
        # Check if high confidence trades performed better
        conf_map: dict[str, list[float]] = {}
        week_trades = [t for t in [] if t.status != "OPEN"]  # placeholder
        for t in week_trades:
            bucket = "HIGH" if t.confidence >= 0.7 else "LOW"
            conf_map.setdefault(bucket, []).append(t.pnl_pct)
        if "HIGH" in conf_map and "LOW" in conf_map:
            avg_high = sum(conf_map["HIGH"]) / len(conf_map["HIGH"])
            avg_low = sum(conf_map["LOW"]) / len(conf_map["LOW"])
            if avg_high > avg_low + 0.2:
                actions.append(f"高置信度交易表现显著优于低置信度（+{avg_high:.2f}% vs {avg_low:.2f}%），建议只做 confidence > 0.65 的信号。")

    # Stoploss optimization
    if s.total_trades >= 3:
        sl_distances = [
            abs(t.entry_price - t.stop_loss) / t.entry_price * 100
            for t in []
            if t.stop_loss > 0 and t.entry_price > 0
        ]
        if sl_distances:
            avg_sl_dist = sum(sl_distances) / len(sl_distances)
            if avg_sl_dist < 0.3:
                actions.append(f"平均止损距离 {avg_sl_dist:.2f}% 偏紧，容易被扫，下周适当放宽至0.5-0.8%。")

    # Position sizing
    if s.risk_pct > 2.0 and s.max_drawdown > 3.0:
        actions.append(f"当前风险 {s.risk_pct}% + MaxDD {s.max_drawdown:.1f}% 组合过于激进，考虑降至1.5-2%。")

    if not actions:
        actions.append("本周表现正常，继续执行现有策略，专注纪律和复盘。")

    return actions


def print_report(s: WeekStats, insights: list[str], actions: list[str]) -> None:
    bar = "=" * 70
    border = "=" * 70

    print(f"\n{bar}")
    print(f"{border}")
    print(f"{border}")
    print(f"  WEEKLY REVIEW  {s.start_date} → {s.end_date}")
    print(f"{border}")
    print(f"{bar}\n")

    # P&L Summary
    pnl_color = "\033[92m" if s.total_pnl >= 0 else "\033[91m"
    reset = "\033[0m"
    print("  【盈亏汇总】")
    print(f"  总交易: {s.total_trades}笔 | 胜: {s.wins} | 亏: {s.losses} | 胜率: {s.win_rate*100:.0f}%")
    print(f"  Total P&L: {pnl_color}{s.total_pnl:+.2f}%{reset}")
    if s.total_trades > 0:
        print(f"  Avg Win: {pnl_color}+{s.avg_win:.3f}%{reset} | Avg Loss: {s.avg_loss:.3f}%")
        print(f"  Expectancy: {s.expectancy:+.3f}%/笔 | Profit Factor: {s.profit_factor:.2f}")
        print(f"  Max Drawdown: {s.max_drawdown:.2f}%")
    print()

    # Best / Worst
    if s.best_trade:
        print(f"  【最佳交易】 {s.best_trade.id} {s.best_trade.symbol} {pnl_color}+{s.best_trade.pnl_pct:.2f}%{reset}")
        print(f"  策略: {s.best_trade.strategy} | 状态: {s.best_trade.regime} | 置信度: {s.best_trade.confidence:.0%}")
        if s.best_trade.idea:
            print(f"  想法: {s.best_trade.idea[:80]}")
        if s.best_trade.reflection:
            print(f"  反思: {s.best_trade.reflection[:80]}")
    if s.worst_trade and s.worst_trade.id != (s.best_trade.id if s.best_trade else ""):
        loss_color = "\033[91m"
        print(f"  【最差交易】 {s.worst_trade.id} {s.worst_trade.symbol} {loss_color}{s.worst_trade.pnl_pct:.2f}%{reset}")
        print(f"  策略: {s.worst_trade.strategy} | 状态: {s.worst_trade.regime}")
        if s.worst_trade.reflection:
            print(f"  反思: {s.worst_trade.reflection[:80]}")
    print()

    # By Strategy
    if s.by_strategy:
        print("  【按策略】")
        for strat, st in sorted(s.by_strategy.items(), key=lambda x: x[1]["expectancy"], reverse=True):
            color = "\033[92m" if st["expectancy"] > 0 else "\033[91m"
            print(
                f"  {strat:20s} | n={st['n']:2d} | "
                f"WR={st['win_rate']*100:.0f}% | "
                f"E={color}{st['expectancy']:+.3f}%{reset} | "
                f"P&L={color}{st['total_pnl']:+.2f}%{reset}"
            )
        print()

    # By Symbol
    if s.by_symbol:
        print("  【按品种】")
        for sym, st in sorted(s.by_symbol.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            color = "\033[92m" if st["total_pnl"] > 0 else "\033[91m"
            print(f"  {sym:10s} | n={st['n']} | P&L={color}{st['total_pnl']:+.2f}%{reset} | E={st['expectancy']:+.3f}%")
        print()

    # By Regime
    if s.by_regime:
        print("  【按市场状态】")
        for reg, st in s.by_regime.items():
            color = "\033[92m" if st["expectancy"] > 0 else "\033[91m"
            print(f"  {reg:20s} | n={st['n']} | E={color}{st['expectancy']:+.3f}%{reset} | PF={st['profit_factor']:.2f}")
        print()

    # Execution issues
    if s.execution_issues:
        print(f"  【执行问题】 {len(s.execution_issues)}笔")
        for t in s.execution_issues:
            print(f"  - {t.id} {t.symbol}: {t.execution_notes[:60]}")
        print()

    # Insights
    if insights:
        print("  【分析洞察】")
        for i, insight in enumerate(insights, 1):
            print(f"  {i}. {insight}")
        print()

    # Action items
    print("  【下周行动计划】")
    for i, action in enumerate(actions, 1):
        print(f"  {i}. {action}")
    print()

    # Common reflections
    if s.common_reflections:
        print("  【交易反思摘录】")
        for ref in s.common_reflections[:5]:
            print(f"  • {ref}")
        print()

    print(f"{bar}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="每周复盘 + 策略迭代")
    parser.add_argument("--week-offset", type=int, default=0, help="查看哪一周（0=本周，1=上周，2=上上周）")
    parser.add_argument("--auto-tune", action="store_true", help="自动调参（基于周度数据微调参数）")
    parser.add_argument("--write-changes", action="store_true", help="将优化建议写入策略文件")
    parser.add_argument("--min-trades", type=int, default=3, help="最少交易笔数才进行深度分析")
    args = parser.parse_args()

    trades = load_trades(JOURNAL_PATH)
    if not trades:
        print("[ERROR] No closed trades found in trade_journal.csv")
        print("先记录几笔交易后再运行复盘: python scripts/add_trade.py")
        sys.exit(1)

    s = analyze_week(trades, args.week_offset)

    if s.total_trades < args.min_trades:
        print(f"[INFO] 本周只有 {s.total_trades} 笔交易（最少需要 {args.min_trades} 笔），跳过深度分析。")
        print("使用 --min-trades 2 可降低门槛。")
        sys.exit(0)

    insights = generate_insights(s, trades)
    actions = generate_action_items(s)
    print_report(s, insights, actions)

    # Auto-tune: suggest parameter adjustments
    if args.auto_tune and s.total_trades >= args.min_trades:
        print("\n[auto-tune] 基于本周数据生成参数调整建议...\n")
        # This would normally feed into the parameter optimization pipeline
        # For now, just print the suggested actions
        print("建议运行以下扫描验证参数:")
        if s.by_strategy:
            best = max(s.by_strategy.items(), key=lambda x: x[1]["expectancy"])
            worst = min(
                (x for x in s.by_strategy.items() if x[1]["n"] >= 2),
                key=lambda x: x[1]["expectancy"],
                default=None,
            )
            if best[1]["expectancy"] > 0:
                print(f"  - {best[0]} 表现最佳，增加该策略权重")
            if worst and worst[1]["expectancy"] < 0:
                print(f"  - {worst[0]} 表现最差，降低该策略权重或暂停")

    if args.write_changes:
        print("\n[write-changes] 功能待实现（需要策略参数配置文件）")
        print("建议手动更新 config/strategy_params.yaml")


if __name__ == "__main__":
    main()
