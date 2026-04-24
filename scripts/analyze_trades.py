#!/usr/bin/env python3
"""
analyze_trades.py — 交易复盘分析
输出：各策略/品种/状态 胜率、盈亏比、Expectancy、Optimal risk%
用法：python scripts/analyze_trades.py
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@dataclass
class Trade:
    id: str
    symbol: str
    date: str
    time: str
    direction: str  # LONG / SELL
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    status: str  # WIN / LOSS / BREAKEVEN
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


def load_trades(path: Path) -> list[Trade]:
    trades: list[Trade] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("id"):
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


def win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.status == "WIN")
    return wins / len(trades)


def avg_win(trades: list[Trade]) -> float:
    wins = [t.pnl_pct for t in trades if t.status == "WIN"]
    return sum(wins) / len(wins) if wins else 0.0


def avg_loss(trades: list[Trade]) -> float:
    losses = [t.pnl_pct for t in trades if t.status == "LOSS"]
    return sum(losses) / len(losses) if losses else 0.0


def expectancy(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wr = win_rate(trades)
    aw = avg_win(trades)
    al = avg_loss(trades)
    return wr * aw + (1 - wr) * al


def profit_factor(trades: list[Trade]) -> float:
    gross_win = sum(t.pnl_abs for t in trades if t.status == "WIN")
    gross_loss = abs(sum(t.pnl_abs for t in trades if t.status == "LOSS"))
    return gross_win / gross_loss if gross_loss else 0.0


def max_drawdown(trades: list[Trade]) -> float:
    """近似最大回撤：从峰值到谷底的最大跌幅"""
    if not trades:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in trades:
        equity *= 1 + t.pnl_pct / 100
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100


def sharpe_estimate(trades: list[Trade]) -> float:
    """年化Sharpe估算（假设日间交易）"""
    if len(trades) < 2:
        return 0.0
    rets = [t.pnl_pct / 100 for t in trades]
    mean_ret = sum(rets) / len(rets)
    variance = sum((r - mean_ret) ** 2 for r in rets) / max(len(rets) - 1, 1)
    std_ret = variance ** 0.5
    if std_ret == 0:
        return 0.0
    # 年化：假设每天1笔，年化252交易日
    annualized = (mean_ret / std_ret) * (252 ** 0.5)
    return annualized


def group_by(trades: list[Trade], key: str) -> dict[str, list[Trade]]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        if key == "strategy":
            g = t.strategy or "UNKNOWN"
        elif key == "symbol":
            g = t.symbol or "UNKNOWN"
        elif key == "regime":
            g = t.regime or "UNKNOWN"
        elif key == "risk_pct":
            g = f"{t.risk_pct:.1f}%"
        elif key == "month":
            g = t.date[:7] if t.date else "UNKNOWN"
        elif key == "status":
            g = t.status or "UNKNOWN"
        else:
            g = "UNKNOWN"
        groups.setdefault(g, []).append(t)
    return groups


def print_stats_table(title: str, groups: dict[str, list[Trade]], sort_key: str = "expectancy") -> None:
    rows = []
    for name, grp in groups.items():
        pf = profit_factor(grp)
        dd = max_drawdown(grp)
        sharpe = sharpe_estimate(grp)
        rows.append(
            {
                "group": name,
                "trades": len(grp),
                "win%": f"{win_rate(grp)*100:.0f}%",
                "avg_win": f"+{avg_win(grp):.2f}%",
                "avg_loss": f"{avg_loss(grp):.2f}%",
                "expectancy": f"{expectancy(grp):.3f}%",
                "profit_factor": f"{pf:.2f}",
                "max_dd": f"{dd:.1f}%",
                "sharpe": f"{sharpe:.2f}",
                "total_pnl": f"+{sum(t.pnl_pct for t in grp):.1f}%" if sum(t.pnl_pct for t in grp) >= 0 else f"{sum(t.pnl_pct for t in grp):.1f}%",
            }
        )

    # Sort
    if sort_key == "expectancy":
        rows.sort(key=lambda r: float(r["expectancy"].replace("%", "").replace("+", "")), reverse=True)
    elif sort_key == "total_pnl":
        rows.sort(key=lambda r: float(r["total_pnl"].replace("%", "").replace("+", "")), reverse=True)
    elif sort_key == "sharpe":
        rows.sort(key=lambda r: float(r["sharpe"]), reverse=True)

    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Group", style="cyan", width=18)
    table.add_column("N", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Avg Win", justify="right")
    table.add_column("Avg Loss", justify="right")
    table.add_column("E(%/trade)", justify="right")
    table.add_column("PF", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Total P&L", justify="right")

    for r in rows:
        total_val = float(r["total_pnl"].replace("%", "").replace("+", ""))
        style = "green" if total_val > 0 else "red"
        table.add_row(
            r["group"],
            r["trades"],
            r["win%"],
            r["avg_win"],
            r["avg_loss"],
            r["expectancy"],
            r["profit_factor"],
            r["max_dd"],
            r["sharpe"],
            f"[{style}]{r['total_pnl']}[/{style}]",
        )

    console.print(table)


def print_trade_detail(trades: list[Trade]) -> None:
    """打印最赚钱和最亏钱的交易"""
    sorted_trades = sorted(trades, key=lambda t: t.pnl_pct, reverse=True)

    console.print("\n[bold green]Top 5 最赚钱交易[/bold green]")
    for t in sorted_trades[:5]:
        console.print(
            f"  [{t.date}] {t.symbol} {t.direction} | "
            f"Entry {t.entry_price} → Exit {t.exit_price} | "
            f"[green]+{t.pnl_pct:.2f}%[/green] | {t.strategy} | {t.regime}"
        )
        if t.idea:
            console.print(f"    Idea: {t.idea[:80]}")
        console.print(f"    Reflection: {t.reflection[:80]}")

    console.print("\n[bold red]Bottom 5 最亏钱交易[/bold red]")
    for t in sorted_trades[-5:]:
        console.print(
            f"  [{t.date}] {t.symbol} {t.direction} | "
            f"Entry {t.entry_price} → Exit {t.exit_price} | "
            f"[red]{t.pnl_pct:.2f}%[/red] | {t.strategy} | {t.regime}"
        )
        if t.reflection:
            console.print(f"    Reflection: {t.reflection[:80]}")


def print_optimization_notes(trades: list[Trade]) -> None:
    """汇总所有优化建议"""
    optimizations = [t.optimization for t in trades if t.optimization and t.optimization != "TBD"]
    if not optimizations:
        console.print("\n[yellow]暂无优化建议（所有交易 optimization 字段为 TBD）[/yellow]")
        return

    console.print("\n[bold cyan]优化建议汇总（去重）[/bold cyan]")
    seen: set[str] = set()
    for opt in optimizations:
        if opt and opt not in seen:
            seen.add(opt)
            console.print(f"  • {opt}")


def print_monthly_pnl(trades: list[Trade]) -> None:
    """按月汇总"""
    months = group_by(trades, "month")
    sorted_months = sorted(months.keys())

    console.print("\n[bold]月度盈亏[/bold]")
    cumulative = 0.0
    for month in sorted_months:
        grp = months[month]
        month_pnl = sum(t.pnl_pct for t in grp)
        cumulative += month_pnl
        n_wins = sum(1 for t in grp if t.status == "WIN")
        style = "green" if month_pnl > 0 else "red"
        console.print(
            f"  {month} | {len(grp)}笔 | "
            f"[{style}]{month_pnl:+.2f}%[/{style}] | "
            f"累计 [{'green' if cumulative > 0 else 'red'}]{cumulative:+.2f}%[/{'green' if cumulative > 0 else 'red'}] | "
            f"{n_wins}/{len(grp)} 胜"
        )


def print_execution_compliance(trades: list[Trade]) -> None:
    """检查计划执行率"""
    if not trades:
        return
    # execution_notes 包含 "按计划" / "偏离" 等关键词
    follow_plan = sum(1 for t in trades if "按计划" in t.execution_notes or "执行正确" in t.execution_notes)
    deviate = sum(1 for t in trades if "偏离" in t.execution_notes or "未按" in t.execution_notes)
    console.print(f"\n[bold]执行纪律[/bold] | 按计划: {follow_plan} | 偏离: {deviate} | 未记录: {len(trades)-follow_plan-deviate}")
    # 按策略看执行率
    by_strategy = group_by(trades, "strategy")
    for strat, grp in by_strategy.items():
        fp = sum(1 for t in grp if "按计划" in t.execution_notes or "执行正确" in t.execution_notes)
        console.print(f"  {strat}: {fp}/{len(grp)} 按计划执行")


def print_equity_curve(trades: list[Trade]) -> None:
    """文字版equity curve（按交易顺序）"""
    if not trades:
        return
    equity = 100.0  # 初始 100
    console.print("\n[bold]Equity Curve（每笔交易后）[/bold]")
    console.print("  Start: 100.00")
    for i, t in enumerate(trades):
        equity *= 1 + t.pnl_pct / 100
        bar = "█" * min(int(equity - 100 + 10), 30)
        marker = "+" if t.pnl_pct > 0 else ""
        console.print(
            f"  [{i+1:3}] {t.date} {t.symbol:8} [{marker}{t.pnl_pct:6.2f}%] "
            f"→ {equity:7.2f} {bar}"
        )
    console.print(f"  End: {equity:.2f}")


def main() -> None:
    journal_path = Path(__file__).parent.parent / "data" / "trade_journal.csv"
    if not journal_path.exists():
        console.print(f"[red]trade_journal.csv not found at {journal_path}[/red]")
        console.print("创建示例交易记录？[y/N]", end=" ")
        return

    trades = load_trades(journal_path)
    if not trades:
        console.print("[yellow]No trades found in journal.[/yellow]")
        return

    console.print(Panel(f"[bold]交易复盘分析[/bold] | 共 {len(trades)} 笔交易 | {trades[0].date} ~ {trades[-1].date}"))

    # Overall
    overall_table = Table(title="Overall", show_header=False, box=None)
    overall_table.add_column("k", style="cyan")
    overall_table.add_column("v", style="white")
    overall_table.add_row("总交易", str(len(trades)))
    overall_table.add_row("Win Rate", f"{win_rate(trades)*100:.1f}%")
    overall_table.add_row("Avg Win", f"+{avg_win(trades):.3f}%")
    overall_table.add_row("Avg Loss", f"{avg_loss(trades):.3f}%")
    overall_table.add_row("Expectancy/trade", f"{expectancy(trades):.3f}%")
    overall_table.add_row("Profit Factor", f"{profit_factor(trades):.2f}")
    overall_table.add_row("Max Drawdown", f"{max_drawdown(trades):.1f}%")
    overall_table.add_row("Sharpe(est)", f"{sharpe_estimate(trades):.2f}")
    overall_table.add_row("Total P&L", f"+{sum(t.pnl_pct for t in trades):.2f}%")
    console.print(overall_table)

    # By strategy
    print_stats_table("By Strategy", group_by(trades, "strategy"), sort_key="expectancy")

    # By symbol
    print_stats_table("By Symbol", group_by(trades, "symbol"), sort_key="total_pnl")

    # By regime
    print_stats_table("By Regime", group_by(trades, "regime"), sort_key="expectancy")

    # By risk%
    print_stats_table("By Risk%", group_by(trades, "risk_pct"), sort_key="expectancy")

    # Monthly
    print_monthly_pnl(trades)

    # Execution compliance
    print_execution_compliance(trades)

    # Top/bottom trades
    print_trade_detail(trades)

    # Optimization
    print_optimization_notes(trades)

    # Equity curve
    print_equity_curve(trades)


if __name__ == "__main__":
    main()
