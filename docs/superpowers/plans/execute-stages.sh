#!/bin/bash
# =============================================================================
# crypto-ai-trader v3 阶段执行脚本
# 使用方式: ./execute-stages.sh [stage-number]
# 不带参数则执行所有可并行的 Stage，带参数只执行对应 Stage
# =============================================================================

set -e

AGENT_MODEL="minimax-m2.7"
AGENT_PROVIDER="minimax-cn"
PLAN_FILE="docs/superpowers/plans/2026-04-21-v3-final-plan.md"
WORKDIR="/Users/zihanma/Desktop/crypto-ai-trader"

echo "=========================================="
echo "crypto-ai-trader v3 Stage Executor"
echo "Plan: $PLAN_FILE"
echo "=========================================="

# Stage 0: 安全修复
execute_stage_0() {
  echo ""
  echo ">>> [Stage 0] 安全修复"
  echo ">>> 目标: 敏感信息扫描 + DB 事务加固"
  echo ">>> 前置: 无"
  echo ""
  hermes delegate \
    --model "$AGENT_MODEL" \
    --provider "$AGENT_PROVIDER" \
    --context "\
你在 /Users/zihanma/Desktop/crypto-ai-trader 工作。

执行 v3 计划的 Stage 0：安全修复。

读取完整计划: $PLAN_FILE
重点关注 Stage 0 的任务描述和 Review Checklist（在文件靠前位置，搜索 'Stage 0 Review Checklist'）。

Stage 0 核心任务:
1. 敏感信息扫描: 运行 scripts/scan_secrets.py，确保无 API key/secret/token 泄露
2. DB 事务加固: 检查 trading/storage/ 下的所有 DB 写入，确保在事务内执行
3. 脚本幂等性: 确保 scripts/ 下的迁移/修复脚本可重复执行

完成所有任务后，对照 Stage 0 Review Checklist 逐项验证，然后输出:
- 已完成的任务清单
- Review Checklist 通过情况（每项通过/失败）
- 发现的问题和解决方案
- 剩余未解决问题的说明
" \
    --goal "完成 Stage 0 安全修复，通过 Stage 0 Review Checklist" \
    --name "stage-0-security"
  echo ">>> [Stage 0] 完成"
}

# Stage 1: 退出策略 100%
execute_stage_1() {
  echo ""
  echo ">>> [Stage 1] 退出策略 100%"
  echo ">>> 目标: ExitEngine YAML 配置化"
  echo ">>> 前置: Stage 0 完成"
  echo ""
  hermes delegate \
    --model "$AGENT_MODEL" \
    --provider "$AGENT_PROVIDER" \
    --context "\
你在 /Users/zihanma/Desktop/crypto-ai-trader 工作。

执行 v3 计划的 Stage 1：退出策略 100%。

读取完整计划: $PLAN_FILE
重点关注 Stage 1 的任务描述和 Review Checklist（搜索 'Stage 1 Review Checklist'）。

Stage 1 核心任务:
1. ExitEngine YAML 配置化: 将硬编码的退出规则移到 config/exit_strategies.yaml
2. 支持 5 种退出策略: trailing_stop / time_based / signal_based / hybrid / emergency
3. ExitRunner 适配新配置格式
4. 单元测试覆盖率 ≥ 95%

完成所有任务后，对照 Stage 1 Review Checklist 逐项验证，然后输出:
- 已完成的任务清单
- Review Checklist 通过情况（每项通过/失败）
- 新增/修改的文件列表
- 发现的问题和解决方案
" \
    --goal "完成 Stage 1 退出策略 100%，通过 Stage 1 Review Checklist" \
    --name "stage-1-exits"
  echo ">>> [Stage 1] 完成"
}

# Stage 2: 回测框架 + 因子库
execute_stage_2() {
  echo ""
  echo ">>> [Stage 2] 回测框架 + 因子库"
  echo ">>> 目标: BacktestEngine + 10+ 因子"
  echo ">>> 前置: Stage 0 完成"
  echo ""
  hermes delegate \
    --model "$AGENT_MODEL" \
    --provider "$AGENT_PROVIDER" \
    --context "\
你在 /Users/zihanma/Desktop/crypto-ai-trader 工作。

执行 v3 计划的 Stage 2：回测框架 + 因子库。

读取完整计划: $PLAN_FILE
重点关注 Stage 2 的任务描述和 Review Checklist（搜索 'Stage 2 Review Checklist'）。

Stage 2 核心任务:
1. BacktestEngine: 实现回测引擎，支持历史数据回放
2. 因子库: 实现 10+ 技术因子 (RSI/EMA/SMA/ATR/BBANDS/MACD/OBV/ADX/STOCH/CCI)
3. 因子 Registry: 统一注册和调用
4. 回测数据隔离: 不影响 live/paper 数据

完成所有任务后，对照 Stage 2 Review Checklist 逐项验证，然后输出:
- 已完成的任务清单
- Review Checklist 通过情况
- 新增/修改的文件列表
" \
    --goal "完成 Stage 2 回测框架 + 因子库，通过 Stage 2 Review Checklist" \
    --name "stage-2-backtest"
  echo ">>> [Stage 2] 完成"
}

# =============================================================================
# 主逻辑
# =============================================================================

if [ -n "$1" ]; then
  case "$1" in
    0) execute_stage_0 ;;
    1) execute_stage_1 ;;
    2) execute_stage_2 ;;
    *) echo "未知 Stage: $1" ;;
  esac
else
  echo ""
  echo "并行执行 Stage 0, 4a, 4b..."
  execute_stage_0 &  PID0=$!
  execute_stage_4a & PID4A=$!
  execute_stage_4b & PID4B=$!
  wait $PID0 $PID4A $PID4B
  echo ">>> 第一批完成"
  echo ""
  echo "第一批完成后，启动 Stage 1, 2, 2b, 6, 7, 8..."
  # 第二批应在第一批验证通过后手动执行
fi

echo ""
echo "=========================================="
echo "执行完成"
echo "=========================================="
