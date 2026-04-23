#!/usr/bin/env python3
"""Stage 3 回测 Pipeline — 带超时监管 + 任务流程追踪。

用法:
    python scripts/run_pipeline.py

超时设置:
    每个任务默认 5 分钟，超时自动 kill + 报告
    Stage 3 回测本身（包含8750根bar）允许 10 分钟
"""
from __future__ import annotations

import os
import sys

# 确保项目根目录在 path 里
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from scripts.watchdog import TaskTracker

WORKDIR = Path(__file__).parent.parent.resolve()
TIMEOUT_DEFAULT = 300   # 5 分钟
TIMEOUT_LONG    = 600   # 10 分钟（回测）


def step_check_deps(tracker: TaskTracker):
    """Step 1: 确认 ruff / mypy / pytest 在 venv 里可用"""
    tracker.run_task(
        "检查依赖工具",
        cmd="cd /Users/zihanma/Desktop/crypto-ai-trader && "
            ".venv/bin/python -c \"import ruff, mypy, pytest; print('deps OK')\"",
        workdir=str(WORKDIR),
        timeout=30,
        description="确认代码质量工具链完整",
    )


def step_ruff_check(tracker: TaskTracker):
    """Step 2: ruff lint"""
    tracker.run_task(
        "ruff lint",
        cmd="cd /Users/zihanma/Desktop/crypto-ai-trader && "
            ".venv/bin/ruff check trading/backtest/engine.py "
            "trading/strategies/active/breakout.py "
            "trading/strategies/active/mean_reversion.py "
            "scripts/run_backtest_stage3.py",
        timeout=TIMEOUT_DEFAULT,
        description="lint 检查，无警告才继续",
    )


def step_mypy_check(tracker: TaskTracker):
    """Step 3: mypy type check"""
    tracker.run_task(
        "mypy strict",
        cmd="cd /Users/zihanma/Desktop/crypto-ai-trader && "
            ".venv/bin/mypy --strict trading/backtest/engine.py "
            "trading/strategies/active/breakout.py "
            "trading/strategies/active/mean_reversion.py "
            "scripts/run_backtest_stage3.py 2>&1",
        timeout=TIMEOUT_DEFAULT,
        description="mypy 严格类型检查，无错误才继续",
    )


def step_run_stage3(tracker: TaskTracker):
    """Step 4: 运行 Stage 3 回测（允许10分钟超时）"""
    result = tracker.run_task(
        "Stage 3 回测",
        cmd="cd /Users/zihanma/Desktop/crypto-ai-trader && "
            ".venv/bin/python scripts/run_backtest_stage3.py 2>&1",
        timeout=TIMEOUT_LONG,
        description="2025年全年数据，8750根1h bar",
    )
    return result


def step_analyze_result(tracker: TaskTracker, result) -> bool:
    """Step 5: 分析回测结果 — 判断是否成功"""
    if result.timed_out:
        tracker.fail("结果分析", reason="回测超时，未能输出报告")
        return False

    if not result.ok:
        # 可能是 Python 崩溃，找一下 traceback
        lines = result.output.splitlines()
        tb = [line for line in lines if "Traceback" in line or "Error:" in line or "Exception" in line]
        reason = tb[-1].strip() if tb else f"exit {result.exit_code}"
        tracker.fail("结果分析", reason=reason)
        return False

    # 检查有没有 "BACKTEST REPORT" 字样
    if "BACKTEST REPORT" not in result.output:
        tracker.fail("结果分析", reason="输出中没有 BACKTEST REPORT，回测脚本可能崩溃")
        return False

    # 提取关键指标
    out = result.output
    def extract(key):
        for line in out.splitlines():
            if key in line:
                parts = line.strip().split()
                for p in parts:
                    if p.replace(".", "").replace("%", "").replace("$", "").replace(",", "").isdigit():
                        return p
        return "?"

    trades   = extract("Total Trades")
    ret_pct  = extract("Total Return")
    sharpe   = extract("Sharpe Ratio")
    mdd      = extract("Max Drawdown")
    win_rate = extract("Win Rate")

    print(f"""
╔══════════════════════════════════════════════════════════╗
║              Stage 3 回测结果摘要                        ║
╠══════════════════════════════════════════════════════════╣
║  总交易数     :  {trades:>8s}                             ║
║  总收益率     :  {ret_pct:>8s}%                           ║
║  夏普比率     :  {sharpe:>8s}                             ║
║  最大回撤     :  {mdd:>8s}%                           ║
║  胜率         :  {win_rate:>8s}                             ║
╚══════════════════════════════════════════════════════════╝
""")

    tracker.succeed("结果分析")
    return True


def run():
    print(f"\n{'='*60}")
    print("  Stage 3 Pipeline — BTCUSDT 回测 + 代码质量门禁")
    print(f"{'='*60}\n")

    tracker = TaskTracker(pipeline_name="Stage 3 回测 Pipeline")
    tracker.add_task("检查依赖工具",   description="ruff / mypy / pytest 可用")
    tracker.add_task("ruff lint",       description="无 lint 警告")
    tracker.add_task("mypy strict",     description="无类型错误")
    tracker.add_task("Stage 3 回测",    description="2025年8750根bar，Breakout+MeanReversion")
    tracker.add_task("结果分析",        description="提取交易数/收益率/夏普/回撤/胜率")

    # ── 执行 pipeline ────────────────────────────────────────────────
    step_check_deps(tracker)

    # 前置检查失败则直接终止
    deps_task = tracker.tasks[0]
    if deps_task.status.value == "❌ failed":
        print("⚠ 依赖工具检查失败，Pipeline 终止。")
        print(tracker.summary())
        sys.exit(1)

    step_ruff_check(tracker)

    # ruff 失败 → 继续但标记
    ruff_task = tracker.tasks[1]
    if ruff_task.status.value == "❌ failed":
        print("⚠ ruff 检查有警告，但继续下一步（lint 问题不阻断执行）")

    step_mypy_check(tracker)

    mypy_task = tracker.tasks[2]
    if mypy_task.status.value == "❌ failed":
        print("⚠ mypy 类型检查失败，Pipeline 终止。")
        print(tracker.summary())
        sys.exit(1)

    result = step_run_stage3(tracker)
    ok = step_analyze_result(tracker, result)

    print(tracker.summary())

    if not ok:
        sys.exit(1)

    print("\n✅ Pipeline 全部完成！")
    return tracker


if __name__ == "__main__":
    run()
