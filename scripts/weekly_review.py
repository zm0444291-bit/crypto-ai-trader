#!/usr/bin/env python3
"""weekly_review.py — Weekly trading performance review and self-iteration.

Run every Monday to:
  1. Load trade journal (live trades from data/trade_journal.csv)
  2. Load backtest results (scan JSON from scripts/enhanced_trend_results.json etc.)
  3. Compute per-strategy, per-session, per-month stats
  4. Apply action-item rules to generate next-week recommendations
  5. Print a formatted report

Usage:
  python scripts/weekly_review.py                                           # journal analysis
  python scripts/weekly_review.py --backtest scripts/enhanced_trend_results.json  # scan analysis
  python scripts/weekly_review.py --backtest scripts/enhanced_trend_results.json --top 20
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).parent.parent
JOURNAL_PATH = ROOT / "data" / "trade_journal.csv"
RESULTS_DIR = ROOT / "backtest_data" / "results"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WeeklyStats:
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_dd: float
    total_return: float
    avg_win: float
    avg_loss: float


@dataclass
class ScanTopConfig:
    mode: str
    params: dict[str, Any]
    total_return: float
    ann_return: float
    num_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_dd: float
    sharpe: float
    score: float
    longs: int
    shorts: int
    avg_bars: float


# ---------------------------------------------------------------------------
# Journal analysis (per-trade)
# ---------------------------------------------------------------------------


def load_journal() -> pd.DataFrame:
    """Load and validate trade journal CSV."""
    if not JOURNAL_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(JOURNAL_PATH)
    df = df[df["id"].notna() & (df["id"] != "")]
    if df.empty:
        return pd.DataFrame()

    for col in ["pnl_pct", "pnl_abs", "atr_pct", "risk_pct", "confidence"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df


def _compute_stats_from_rets(rets: list[float]) -> WeeklyStats:
    """Compute WeeklyStats from a list of percentage returns."""
    if not rets:
        return WeeklyStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(rets)
    wr = len(wins) / n if n else 0
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    total_ret = sum(rets)
    wins_abs = [abs(r) for r in wins]
    losses_abs = [abs(r) for r in losses]
    pf = sum(wins_abs) / (sum(losses_abs) + 1e-9)
    expectancy = wr * avg_w + (1 - wr) * avg_l

    # Equity curve DD
    eq, peak, max_dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r / 100
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    return WeeklyStats(
        n_trades=n,
        win_rate=wr * 100,
        profit_factor=pf,
        expectancy=expectancy,
        max_dd=max_dd * 100,
        total_return=total_ret,
        avg_win=avg_w,
        avg_loss=avg_l,
    )


def _analyze_by_col(trades_df: pd.DataFrame, col: str) -> dict[str, WeeklyStats]:
    """Group by a column and compute stats per group."""
    results: dict[str, WeeklyStats] = {}
    for val, group in trades_df.groupby(col, dropna=False):
        key = str(val) if val is not None else "Unknown"
        rets = group["pnl_pct"].dropna().tolist()
        results[key] = _compute_stats_from_rets(rets)
    return results


def _generate_action_items(stats: WeeklyStats) -> list[str]:
    """Apply threshold rules to generate next-week recommendations."""
    actions: list[str] = []

    if stats.n_trades == 0:
        actions.append("[INFO] No trades recorded. Check signal generation.")
        return actions

    if stats.win_rate < 45:
        actions.append(
            f"[RAISE] Win rate {stats.win_rate:.1f}% < 45%. "
            "Raise entry threshold: confidence > 0.70."
        )
    elif stats.win_rate < 50:
        actions.append(
            f"[WATCH] Win rate {stats.win_rate:.1f}% < 50%. "
            "Monitor closely — tighten entry if < 45% next week."
        )

    if stats.expectancy < 0.15:
        actions.append(
            f"[ADJUST] Expectancy {stats.expectancy:.4f}% < 0.15%/trade. "
            "Widen SL slightly OR tighten TP."
        )

    if stats.profit_factor < 1.0:
        actions.append(
            f"[STOP] PF {stats.profit_factor:.2f} < 1.0. "
            "Reduce risk to 1.5% until validated."
        )
    elif stats.profit_factor < 1.5:
        actions.append(
            f"[WATCH] PF {stats.profit_factor:.2f} < 1.5. "
            "Review losing setups."
        )

    if stats.max_dd > 5:
        actions.append(
            f"[HARD STOP] Max DD {stats.max_dd:.1f}% > 5%. "
            "Cap risk at 1.5% until DD < 3%."
        )
    elif stats.max_dd > 3:
        actions.append(
            f"[CAUTION] Max DD {stats.max_dd:.1f}% > 3%. "
            "Reduce to 1.5% risk next week."
        )

    if not actions:
        actions.append("[OK] All metrics within acceptable range. Maintain current settings.")

    return actions


def _print_action_items(actions: list[str]) -> None:
    for a in actions:
        prefix = a[:7]
        rest = a[7:].strip()
        if prefix.startswith("[OK]"):
            print(f"    \033[92m✓\033[0m {rest}")
        elif prefix.startswith("[STOP]") or prefix.startswith("[HARD STOP]"):
            print(f"    \033[91m✗ {rest}\033[0m")
        elif prefix.startswith("[RAISE]") or prefix.startswith("[ADJUST]"):
            print(f"    \033[93m→\033[0m {rest}")
        elif prefix.startswith("[SCALE]"):
            print(f"    \033[94m↑\033[0m {rest}")
        elif prefix.startswith("[SESSION]") or prefix.startswith("[PATTERN]"):
            print(f"    \033[96m↪\033[0m {rest}")
        else:
            print(f"    • {a}")


def run_journal_review(df: pd.DataFrame, week_label: str) -> None:
    """Run full weekly review from journal CSV."""
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Compute overall stats
    all_rets = df["pnl_pct"].dropna().tolist()
    stats = _compute_stats_from_rets(all_rets)

    # Per-session
    session_stats = _analyze_by_col(df, "session") if "session" in df.columns else {}
    # Per-strategy/pattern
    pattern_stats = (
        _analyze_by_col(df, "strategy") if "strategy" in df.columns else
        _analyze_by_col(df, "pattern") if "pattern" in df.columns else {}
    )
    # Per-month
    monthly_stats: dict[str, WeeklyStats] = {}
    if "date" in df.columns:
        df = df.copy()
        df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
        monthly_stats = _analyze_by_col(df, "month")

    actions = _generate_action_items(stats)

    print()
    print("=" * 70)
    print(f"  WEEKLY REVIEW (JOURNAL)  —  {week_label}  ({now_s})")
    print("=" * 70)

    print()
    print(f"  {'Metric':<20} {'Value':>12}")
    print(f"  {'-'*20} {'-'*12}")
    print(f"  {'Total Trades':<20} {stats.n_trades:>12}")
    print(f"  {'Win Rate':<20} {stats.win_rate:>11.1f}%")
    print(f"  {'Profit Factor':<20} {stats.profit_factor:>12.2f}")
    print(f"  {'Expectancy':<20} {stats.expectancy:>12.4f}%")
    print(f"  {'Max Drawdown':<20} {stats.max_dd:>11.1f}%")
    print(f"  {'Total Return':<20} {stats.total_return:>11.2f}%")
    print(f"  {'Avg Win':<20} {stats.avg_win:>12.3f}%")
    print(f"  {'Avg Loss':<20} {stats.avg_loss:>12.3f}%")

    if session_stats:
        print()
        print("  By Session:")
        print(f"  {'Session':<15} {'N':>4} {'WR%':>6} {'PF':>6} {'Ret%':>8}")
        print(f"  {'-'*15} {'-'*4} {'-'*6} {'-'*6} {'-'*8}")
        for sess in sorted(session_stats, key=lambda x: session_stats[x].total_return, reverse=True):
            s = session_stats[sess]
            color = "\033[92m" if s.total_return >= 0 else "\033[91m"
            reset = "\033[0m"
            print(
                f"  {sess:<15} {s.n_trades:>4} {s.win_rate:>5.1f}% "
                f"{s.profit_factor:>6.2f} {color}{s.total_return:>+7.2f}%{reset}"
            )

    if pattern_stats:
        print()
        print("  By Strategy/Pattern:")
        print(f"  {'Strategy':<20} {'N':>4} {'WR%':>6} {'PF':>6} {'Ret%':>8} {'E%':>8}")
        print(f"  {'-'*20} {'-'*4} {'-'*6} {'-'*6} {'-'*8} {'-'*8}")
        for pat in sorted(pattern_stats, key=lambda x: pattern_stats[x].total_return, reverse=True):
            s = pattern_stats[pat]
            color = "\033[92m" if s.total_return >= 0 else "\033[91m"
            reset = "\033[0m"
            print(
                f"  {pat:<20} {s.n_trades:>4} {s.win_rate:>5.1f}% "
                f"{s.profit_factor:>6.2f} {color}{s.total_return:>+7.2f}%{reset} "
                f"{s.expectancy:>+7.4f}%"
            )

    if monthly_stats:
        print()
        print("  Monthly:")
        print(f"  {'Month':<10} {'N':>4} {'WR%':>6} {'Ret%':>8}")
        print(f"  {'-'*10} {'-'*4} {'-'*6} {'-'*8}")
        for month in sorted(monthly_stats):
            s = monthly_stats[month]
            color = "\033[92m" if s.total_return >= 0 else "\033[91m"
            reset = "\033[0m"
            print(
                f"  {month:<10} {s.n_trades:>4} {s.win_rate:>5.1f}% "
                f"{color}{s.total_return:>+7.2f}%{reset}"
            )

    # Recent trades
    if not df.empty:
        print()
        print("  Recent Trades (last 10):")
        print(f"  {'Date':<12} {'Dir':<4} {'Entry':>8} {'Exit':>8} {'P&L%':>8} {'Status':<10} {'Strategy'}")
        print(f"  {'-'*12} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*20}")
        for _, row in df.tail(10).iterrows():
            pnl = float(row.get("pnl_pct", 0))
            color = "\033[92m" if pnl > 0 else "\033[91m"
            reset = "\033[0m"
            date_s = str(row.get("date", ""))[:10] if pd.notna(row.get("date")) else ""
            print(
                f"  {date_s:<12} {str(row.get('dir', '')):<4} "
                f"{float(row.get('entry_price', 0)):>8.1f} "
                f"{float(row.get('exit_price', 0)):>8.1f} "
                f"{color}{pnl:>+7.3f}%{reset} "
                f"{str(row.get('status', '')):<10} "
                f"{str(row.get('strategy', ''))[:20]}"
            )

    print()
    print("  Action Items:")
    _print_action_items(actions)

    print()
    print(f"  Report generated: {now_s}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Scan results analysis (per-config aggregated stats)
# ---------------------------------------------------------------------------


def load_scan_results(path: str) -> list[dict[str, Any]]:
    """Load scan results JSON (list of per-config dicts)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return []


def top_configs(results: list[dict[str, Any]], top_n: int = 20) -> list[ScanTopConfig]:
    """Return top-N configs sorted by score."""
    scored = [r for r in results if isinstance(r, dict) and "score" in r]
    scored.sort(key=lambda x: x["score"], reverse=True)
    configs: list[ScanTopConfig] = []
    for r in scored[:top_n]:
        try:
            configs.append(ScanTopConfig(
                mode=r.get("mode", "UNKNOWN"),
                params=r.get("params", {}),
                total_return=float(r.get("total_return", 0)),
                ann_return=float(r.get("ann_return", 0)),
                num_trades=int(r.get("num_trades", 0)),
                win_rate=float(r.get("win_rate", 0)),
                avg_win=float(r.get("avg_win", 0)),
                avg_loss=float(r.get("avg_loss", 0)),
                profit_factor=float(r.get("profit_factor", 0)),
                max_dd=float(r.get("max_dd", 0)),
                sharpe=float(r.get("sharpe", 0)),
                score=float(r.get("score", 0)),
                longs=int(r.get("longs", 0)),
                shorts=int(r.get("shorts", 0)),
                avg_bars=float(r.get("avg_bars", 0)),
            ))
        except (TypeError, ValueError):
            continue
    return configs


def run_scan_review(results: list[dict[str, Any]], week_label: str, top_n: int) -> None:
    """Run review from scan results (aggregated per-config, not per-trade)."""
    now_s = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    configs = top_configs(results, top_n)

    if not configs:
        print("[ERROR] No valid scan results found.")
        return

    # Overall aggregate across top configs
    total_trades = sum(c.num_trades for c in configs)
    avg_wr = sum(c.win_rate * c.num_trades for c in configs) / max(total_trades, 1)
    avg_pf = sum(c.profit_factor * c.num_trades for c in configs) / max(total_trades, 1)
    avg_ret = sum(c.total_return * c.num_trades for c in configs) / max(total_trades, 1)
    avg_dd = sum(c.max_dd * c.num_trades for c in configs) / max(total_trades, 1)
    avg_score = sum(c.score for c in configs) / len(configs)

    print()
    print("=" * 70)
    print(f"  WEEKLY REVIEW (SCAN)  —  {week_label}  ({now_s})")
    print("=" * 70)

    print()
    print(f"  Scan: {len(results):,} total configs  |  Showing top {len(configs)} by Score")
    print()
    _top_label = f"Top-{len(configs)}-Avg"
    _wr_avg = avg_wr * 100 if avg_wr <= 1.0 else avg_wr
    _wr_best = configs[0].win_rate * 100 if configs[0].win_rate <= 1.0 else configs[0].win_rate
    _ret_avg = avg_ret * 100  # multiplier -> %
    _ret_best = configs[0].total_return * 100  # multiplier -> %
    _dd_avg = avg_dd  # already %
    _dd_best = configs[0].max_dd  # already %
    print(f"  {'Metric':<22} {_top_label:>12} {'Best':>12}")
    print(f"  {'-'*22} {'-'*12} {'-'*12}")
    print(f"  {'Score':<22} {avg_score:>12.4f} {configs[0].score:>12.4f}")
    print(f"  {'Total Return %':<22} {_ret_avg:>12.2f} {_ret_best:>12.2f}")
    print(f"  {'Ann Return %':<22} {sum(c.ann_return for c in configs)/len(configs):>12.2f} {configs[0].ann_return:>12.2f}")
    print(f"  {'Win Rate %':<22} {_wr_avg:>12.1f} {_wr_best:>12.1f}")
    print(f"  {'Profit Factor':<22} {avg_pf:>12.2f} {configs[0].profit_factor:>12.2f}")
    print(f"  {'Max Drawdown %':<22} {_dd_avg:>12.2f} {_dd_best:>12.2f}")
    print(f"  {'Total Trades':<22} {total_trades:>12} {configs[0].num_trades:>12}")
    print(f"  {'Longs / Shorts':<22} {'—':>12} {configs[0].longs:>5}/{configs[0].shorts:<5}")

    print()
    print(f"  Top {len(configs)} Configs (sorted by Score):")
    print()
    print(
        f"  {'#':<3} {'Mode':<16} {'SL':>4} {'TP':>4} {'N':>5} "
        f"{'WR%':>6} {'PF':>6} {'DD%':>6} {'Ret%':>8} {'Score':>7}"
    )
    print(
        f"  {'-'*3} {'-'*16} {'-'*4} {'-'*4} {'-'*5} "
        f"{'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7}"
    )
    for i, c in enumerate(configs, 1):
        p = c.params
        sl = p.get("sl", p.get("sl_atr", "?")) if isinstance(p, dict) else "?"
        tp = p.get("tp", p.get("tp_atr", "?")) if isinstance(p, dict) else "?"
        mode = c.mode[:16]
        # win_rate and total_return stored as ratio, convert to % for display
        wr_display = c.win_rate * 100 if c.win_rate <= 1.0 else c.win_rate
        # total_return: multiplier (e.g. 9.09 = 9.09x)
        # ann_return: already annualized %
        # win_rate: stored as ratio (<=1) → ×100; already % (>1) → no change
        # max_dd: stored as % (values like 0.94, 1.2, etc.)
        ret_display = c.total_return * 100  # multiplier → %
        dd_display = c.max_dd  # already % (e.g. 0.94 = 0.94%)
        print(
            f"  {i:<3} {mode:<16} {str(sl):>4} {str(tp):>4} {c.num_trades:>5} "
            f"{wr_display:>5.1f}% {c.profit_factor:>6.2f} {dd_display:>5.2f}% "
            f"{ret_display:>+7.2f}% {c.score:>7.4f}"
        )

    print()
    best = configs[0]
    print(f"  Best Config: {best.mode}")
    print(f"  Params: {best.params}")
    print("  → Use this config for next week's backtest/paper run.")

    print()
    print(f"  Report generated: {now_s}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly trading review")
    parser.add_argument(
        "--backtest",
        type=str,
        default=None,
        help="Path to scan results JSON (aggregated per-config)",
    )
    parser.add_argument(
        "--journal",
        type=str,
        default=None,
        help="Path to trade journal CSV (default: data/trade_journal.csv)",
    )
    parser.add_argument(
        "--week",
        type=str,
        default=None,
        help="Week label e.g. '2026-W16' (default: this week)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top configs to show for scan review (default: 20)",
    )
    args = parser.parse_args()

    week_label = args.week or _current_week()

    # Scan mode
    if args.backtest:
        results = load_scan_results(args.backtest)
        if not results:
            sys.exit(1)
        run_scan_review(results, week_label, args.top)
        return

    # Journal mode
    journal_path = Path(args.journal) if args.journal else JOURNAL_PATH
    if not journal_path.exists():
        print("[INFO] No trade journal found.")
        print(f"  Expected: {journal_path}")
        print("  Run live trading to populate the journal,")
        print("  or use --backtest to analyze scan results.")
        sys.exit(0)

    df = load_journal()
    if df.empty:
        print("[INFO] Journal is empty. No trades recorded.")
        sys.exit(0)

    run_journal_review(df, week_label)


def _current_week() -> str:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


if __name__ == "__main__":
    main()
