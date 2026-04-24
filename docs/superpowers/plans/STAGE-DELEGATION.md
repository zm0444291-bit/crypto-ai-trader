# v3 阶段委托执行指南

## 核心机制

使用 `delegate_task` 工具批量委托 Agent，每个 Stage 由独立 Agent 完成，返回结构化报告，最后汇总。

## 分批策略

```
[批次 1] Stage 0, 4a, 4b    ← 完全并行，无依赖
[批次 2] Stage 1, 2, 2b, 6, 7, 8  ← 等待批次 1 完成
[批次 3] Stage 5           ← 等待 Stage 2/2b 完成
[批次 4] Stage 3           ← 等待 Stage 5 完成
[批次 5] Stage 9           ← 等待 Stage 8 完成
[批次 6] Stage 10          ← 等待 Stage 9 完成
```

## 执行命令模板

每个 Stage 委托时，使用以下 prompt 模板：

```
## System Prompt
你是一个专业、谨慎的量化交易系统开发者。你必须严格按照 Review Checklist 交付每个 Stage，不跳跃步骤，不过度承诺。

## Context
工作目录: /Users/zihanma/Desktop/crypto-ai-trader
完整计划: docs/superpowers/plans/2026-04-21-v3-final-plan.md
CLAUDE.md: CLAUDE.md

## 你的任务
执行 v3 计划的 Stage [N]：[阶段名称]

步骤：
1. 读取 $PLAN_FILE 中 Stage [N] 的任务描述和 Review Checklist
2. 执行所有任务（见计划中的任务列表）
3. 对照 Review Checklist 逐项验证
4. 用自动化检查命令验证（mypy --strict / ruff / pytest）
5. 输出结构化报告（见下方格式）

## 输出报告格式（JSON）
{
  "stage": "Stage [N]",
  "status": "completed|partial|blocked",
  "completed_tasks": ["任务1", "任务2", ...],
  "failed_tasks": ["任务X (原因)"],
  "review_checklist": {
    "automation_passed": true/false,
    "items": [
      {"item": "VA-X.X", "passed": true/false, "evidence": "pytest输出或文件路径"},
      ...
    ]
  },
  "files_changed": ["file1", "file2"],
  "issues_found": ["问题描述"],
  "next_blockers": ["当前无法解决的问题"]
}
```

## 汇总方式

所有批次完成后，将各 Stage 的 JSON 报告汇总到一份总报告：

```python
import json

reports = [
    # Stage 0 报告,
    # Stage 1 报告,
    # ...
]

overall = {
    "total_stages": 11,
    "completed": sum(1 for r in reports if r["status"] == "completed"),
    "blocked": [r["stage"] for r in reports if r["status"] == "blocked"],
    "stage_details": reports
}
```

---

## 实际执行命令

要执行某个 Stage，在对话中告诉我："执行 Stage X"，我会用 `delegate_task` 工具为你启动对应 Agent。

---

## 当前状态

| Stage | 状态 | 执行批次 | 报告 |
|-------|------|---------|------|
| Stage 0 | ✅ completed | 批次 1 | reports/stage-0-security.md |
| Stage 1 | 待执行 | 批次 2 | — |
| Stage 2 | 待执行 | 批次 2 | — |
| Stage 2b | 待执行 | 批次 2 | — |
| Stage 3 | 待执行 | 批次 4 | — |
| Stage 4a | 待执行 | 批次 1 | — |
| Stage 4b | 待执行 | 批次 1 | — |
| Stage 5 | 待执行 | 批次 3 | — |
| Stage 6 | 待执行 | 批次 2 | — |
| Stage 7 | 待执行 | 批次 2 | — |
| Stage 8 | 待执行 | 批次 2 | — |
| Stage 9 | 待执行 | 批次 5 | — |
| Stage 10 | 待执行 | 批次 6 | — |
