# crypto-ai-trader 100% 完成度提升计划

> 版本: v3.0 Final（修正验收标准 + 代码审查机制）
> 生成: 2026-04-21
> 目标: 所有模块 100% 完成，支持 24h 实时盯盘 + 综合分析执行买卖，最终解锁实盘

---

## 零、代码审查机制

### CR-1：每个 Agent 必须完成代码审查才能合并

**审查流程**：

```
Agent 完成编码
    ↓
Agent 创建 PR（标题格式: [Stage-X] Task-Description）
    ↓
自动检查（必须全部通过）:
  - .venv/bin/mypy --strict 检查通过
  - .venv/bin/ruff check . 检查通过
  - .venv/bin/pytest tests/unit/ -v --tb=short 检查通过
  - 新增测试覆盖率: 核心模块不得低于 90%
    ↓
Human Reviewer（Owner 或指定人员）review
  - 检查逻辑正确性
  - 检查边界情况处理
  - 检查测试充分性
  - 检查文档是否更新
    ↓
合并条件（全部满足）:
  - CI 全部 green
  - Human Review 至少 1 人 approved
  - 没有 unresolved comments
```

**代码风格**：
- 类型注解必须完整（`--strict` mypy）
- docstring 覆盖所有 public 函数
- 敏感操作（live trading、参数变更）必须有日志
- 禁止 hardcoded secrets

**PR 描述模板**：

````markdown
## 阶段/任务
- Stage: X
- Task: T.X.Y

## 改动摘要
<!-- 一句话描述改动 -->

## 改动详情
<!-- 列表列出所有修改的文件和理由 -->

## 验收标准检查
- [ ] 自动化检查全部通过（mypy/ruff/pytest）
- [ ] 新增测试覆盖率 ≥ 90%（核心模块）
- [ ] 功能验证: <!-- 具体操作步骤 -->
- [ ] 结果: <!-- 预期输出 -->

## 风险评估
- 是否有破坏性改动: 是/否
- 是否影响现有功能: 是/否（若是，列出测试证明无回归）

## 依赖
- 前置 Stage/Task: <!-- 无则填无 -->
- 待审查的并行 Stage/Task: <!-- 无则填无 -->
````

### CR-2：测试覆盖率门槛

| 模块类别 | 最低覆盖率 |
|---------|---------|
| 核心模块（execution/risk/state/paper_cycle） | ≥ 95% |
| 高风险模块（live_executor/healer/risk） | ≥ 90% |
| 中等风险（indicators/strategies/exits） | ≥ 85% |
| 低风险（notifications/dashboard_api） | ≥ 75% |
| 测试本身（tests/） | 不计覆盖率 |

**覆盖率检测命令**：
```bash
# 核心模块详细报告
.venv/bin/pytest --cov=trading/execution --cov=trading/risk \
    --cov=trading/runtime/paper_cycle \
    --cov-report=term-missing --cov-report=html

# 全部模块汇总
.venv/bin/pytest --cov=trading --cov-report=term \
    --cov-fail-under=85
```

### CR-3：集成测试门槛

每个 Stage 完成后必须通过集成测试：

```
Stage 0 完成后 → test_stage0_safe_mode
Stage 1 完成后 → test_stage1_exit_engine_integration
Stage 2 完成后 → test_stage2_backtest_integration
Stage 5 完成后 → test_stage5_risk_chain_integration
Stage 10 完成后 → test_stage10_live_mode_integration
```

---

## 一、现状总览

| 模块 | 当前 | 目标 | 缺口 |
|------|------|------|------|
| 核心交易引擎 | 90% | 100% | 出场逻辑串联、runner 异常处理 |
| 风控系统 | 85% | 100% | consecutive_losses 跨 symbol 泄漏、风控强制执行链路 |
| 执行层 | 70% | 100% | slippage=0 高估、Live Executor 串联、binance_filters 完整 |
| 数据摄取 | 70% | 100% | 多 symbol 并行摄取、数据质量告警、数据持久化缓冲 |
| AI 评分 | 70% | 100% | 评分标准未经回测验证、AI 输出结构化、评分历史分析 |
| 退出策略 | 60% | 100% | 止损/止盈/time_exit 未串联、ExitEngine 未接入 cycle |
| 策略研究 | 40% | 100% | 无因子库、无回测框架、无参数优化 |
| Dashboard | 70% | 100% | Extensions 未实现（降级为内置功能）、无实时持仓盯盘 UI |
| 通知系统 | 65% | 100% | 告警分级、无 WebSocket 实时推送、通知审批流 |
| 24/7 运行 | 70% | 100% | 无自动故障恢复、无运行时自检、无日志结构化 |
| 测试 | 70% | 100% | pytest 超时、覆盖率不足、无集成测试 |
| 文档 | 65% | 100% | 无 API 文档、无用户手册、无 runbook |

---

## 二、总体阶段划分

```
【关键路径】
阶段 0：安全修复（即刻，1-3 天）
阶段 1：退出策略 100%（1-2 周）
阶段 2：回测框架 + 因子库（3-4 周）
阶段 2b：数据迁移 + Schema 扩展（与阶段 2 并行，1 周）
阶段 5.1-5.2：风控链路 100%（2 周）
阶段 3：策略多元化（2-3 周）
阶段 9：实盘解锁评审（1-2 周）
阶段 10：实盘交易（小资金灰度，2-4 周）

【可并行路径】
阶段 4：Dashboard 100% + 实时盯盘（3-4 周）
阶段 6：通知系统 100%（1 周）
阶段 7：24/7 运维体系 100%（2 周）
阶段 8：测试 100% + 文档 100%（2-3 周）
```

**总工期：14 个月**

---

## 三、阶段 0：安全修复（即刻，1-3 天）

### T0.1: Paper slippage 按币种分级配置

**改动文件**：
- `trading/execution/paper_executor.py`
- `config/execution.yaml`（新建）

**实现**：
```python
SLIPPAGE_TIERS = {
    "BTCUSDT": Decimal("5"),    # $5 per 1 BTC
    "ETHUSDT": Decimal("8"),    # $8 per 1 ETH
    "BNBUSDT": Decimal("10"),
    "SOLUSDT": Decimal("25"),
    "default": Decimal("50"),
}
```

**验收标准**（必须全部通过）：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-0.1.1 | `PaperExecutor.calculate_slippage("BTCUSDT")` 返回 `Decimal("5")` | `python -c "from trading.execution.paper_executor import SLIPPAGE_TIERS; print(SLIPPAGE_TIERS['BTCUSDT'])"` 输出 `5` |
| VA-0.1.2 | `BTCUSDT` 买入 0.01 BTC，slippage = 0.05 USDT | pytest `test_paper_slippage_btcusdt` |
| VA-0.1.3 | `SOLUSDT` 买入 10 SOL，slippage = 0.25 USDT | pytest `test_paper_slippage_solusdt` |
| VA-0.1.4 | config/execution.yaml 包含 slippage_tiers 节点 | `grep slippage_tiers config/execution.yaml` 有输出 |
| VA-0.1.5 | 覆盖率 ≥ 95%（核心模块） | `pytest --cov=trading/execution --cov-fail-under=95` |

**代码审查清单**：
- [ ] SLIPPAGE_TIERS 为 class-level 常量（非函数内局部变量）
- [ ] Decimal 类型全程使用（无 float 混用）
- [ ] 新增测试覆盖所有 tier 档位

---

### T0.2: Runner 异常分级处理

**改动文件**：
- `trading/runtime/runner.py`

**实现**：
```python
class APIFailureDegradation:
    def __init__(self, telegram_client):
        self.failure_counts: dict[str, int] = {}  # symbol -> count
        self.frozen_symbols: dict[str, datetime] = {}  # symbol -> unfreeze_time
        self.telegram = telegram_client

    def handle_market_data_failure(self, symbol: str) -> bool:
        """返回 True=跳过该 symbol，False=不跳过"""
        self.failure_counts[symbol] = self.failure_counts.get(symbol, 0) + 1
        if self.failure_counts[symbol] >= 3:
            self._freeze_symbol(symbol, minutes=30)
            self.telegram.send(
                level=AlertLevel.ERROR,
                msg=f"Market data failure 3次，冻结 {symbol} 30分钟"
            )
            return True
        self.telegram.send(
            level=AlertLevel.WARNING,
            msg=f"Market data failure {symbol} ({self.failure_counts[symbol]}/3)"
        )
        return True  # 始终跳过，数据失败不冒进

    def handle_order_failure(self, symbol: str, error: Exception) -> str:
        """返回 'freeze' | 'retry' | 'abort'"""
        self.failure_counts[symbol] = self.failure_counts.get(symbol, 0) + 1
        if isinstance(error, BinanceAPIException):
            if error.code in (-1003, -1010, 429):  # 限流/断流
                self._backoff(symbol, delay=60)
                return 'retry'
        if self.failure_counts[symbol] >= 3:
            self._freeze_symbol(symbol, minutes=60)
            self.telegram.send(level=AlertLevel.CRITICAL,
                msg=f"Order failure 3次，冻结 {symbol} 60分钟: {error}")
            return 'abort'
        return 'retry'

    def _freeze_symbol(self, symbol: str, minutes: int):
        self.frozen_symbols[symbol] = datetime.now() + timedelta(minutes=minutes)
        self.failure_counts[symbol] = 0  # 重置计数

    def is_symbol_frozen(self, symbol: str) -> bool:
        if symbol not in self.frozen_symbols:
            return False
        if datetime.now() >= self.frozen_symbols[symbol]:
            del self.frozen_symbols[symbol]
            return False
        return True
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-0.2.1 | 同一 symbol 第3次 market_data_failure 后，`is_symbol_frozen()` 返回 `True` | pytest `test_runner_freeze_after_3_failures` |
| VA-0.2.2 | 冻结 30 分钟后自动解冻 | pytest `test_runner_unfreeze_after_timeout` |
| VA-0.2.3 | 限流错误返回 `retry`，非限流3次失败返回 `abort` | pytest `test_runner_error_classification` |
| VA-0.2.4 | Telegram 告警发送（mock 验证调用参数） | pytest `test_runner_telegram_alert` |
| VA-0.2.5 | 冻结期间 runner 跳过该 symbol 的交易 | pytest `test_runner_skip_frozen_symbol` |
| VA-0.2.6 | 覆盖率 ≥ 95% | `pytest --cov=trading/runtime/runner --cov-fail-under=95` |

**代码审查清单**：
- [ ] 所有异常分类有文档注释
- [ ] 时间相关逻辑使用 datetime（timezone-aware）
- [ ] 失败计数在 freeze 时重置
- [ ] Telegram 调用在主逻辑之外（失败不影响交易）

---

### T0.3: consecutive_losses 按 symbol 隔离

**改动文件**：
- `trading/risk/state.py`

**实现**：
```python
# Before (int)
consecutive_losses: int

# After (dict)
consecutive_losses: dict[str, int]  # {symbol: count}

# 使用处
def record_loss(self, symbol: str):
    self.consecutive_losses[symbol] = self.consecutive_losses.get(symbol, 0) + 1

def record_win(self, symbol: str):
    self.consecutive_losses[symbol] = 0

def get_consecutive_losses(self, symbol: str) -> int:
    return self.consecutive_losses.get(symbol, 0)

# 风控判断
if self.get_consecutive_losses(symbol) >= 3:
    return RiskDecision.REJECT(f"consecutive_losses={losses}≥3")
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-0.3.1 | `BTCUSDT` 连续亏损 3 次不影响 `ETHUSDT` 的计数 | pytest `test_consecutive_losses_symbol_isolation` |
| VA-0.3.2 | `record_win("BTCUSDT")` 后 `BTCUSDT` 计数归零，`ETHUSDT` 不受影响 | pytest `test_consecutive_losses_win_resets_only_target` |
| VA-0.3.3 | 序列化/反序列化后数据一致 | pytest `test_consecutive_losses_serialization` |
| VA-0.3.4 | 历史数据迁移脚本正确处理 dict 格式 | 手动运行迁移脚本后 DB 查询一致 |
| VA-0.3.5 | 覆盖率 ≥ 95% | `pytest --cov=trading/risk/state --cov-fail-under=95` |

**代码审查清单**：
- [ ] `get_consecutive_losses(symbol)` 不存在的 symbol 返回 0（而非抛异常）
- [ ] 所有使用旧 `consecutive_losses` 的地方已更新
- [ ] DB 迁移脚本有回滚方案

---

### T0.4: 历史 Paper slippage 回溯修正

**改动文件**：
- `scripts/backfill_slippage.py`（新建）
- `trading/storage/repositories.py`

**实现**：
```python
# scripts/backfill_slippage.py
"""
Usage: python scripts/backfill_slippage.py

对 data/crypto_ai_trader.sqlite3 中 execution_records 表
slippage=0 的记录重新计算并回写。
"""
import sqlite3
from decimal import Decimal
from pathlib import Path

SLIPPAGE_TIERS = {...}  # 同 T0.1

def backfill():
    db_path = Path(__file__).parent.parent / "data" / "crypto_ai_trader.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, symbol, side, quantity, price FROM execution_records 
        WHERE slippage = 0 OR slippage IS NULL
    """)
    rows = cursor.fetchall()
    
    for row in rows:
        id_, symbol, side, quantity, price = row
        slippage_tier = SLIPPAGE_TIERS.get(symbol, SLIPPAGE_TIERS["default"])
        slippage = Decimal(str(quantity)) * slippage_tier / Decimal("10000")  # bps
        # ... 计算并回写
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-0.4.1 | 脚本执行不抛异常 | `python scripts/backfill_slippage.py` 返回 exit code 0 |
| VA-0.4.2 | 回写后 slippage 值与 SLIPPAGE_TIERS 一致 | DB 查询: `SELECT symbol, slippage FROM execution_records WHERE slippage > 0` |
| VA-0.4.3 | 修改写入日志（每条记录一行） | `cat logs/backfill_slippage.log` 有输出 |
| VA-0.4.4 | 脚本可重复执行（幂等） | 运行两次，第二次无新增修改 | VA-0.4.5 | 有回滚脚本（`scripts/rollback_slippage.py`） | 文档中有回滚说明 |

**代码审查清单**：
- [ ] 修改前有 `SELECT` 预览（dry-run 模式）
- [ ] 所有 DB 写入在事务内
- [ ] 脚本可幂等执行

---

### Stage 0 Review Checklist（安全修复）

**PR 标题格式**：`[Stage-0] 安全修复`

**自动化检查（必须全部通过）**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/execution/paper_executor.py \
    trading/runtime/runner.py trading/risk/state.py

# 2. 代码风格
.venv/bin/ruff check trading/execution/paper_executor.py \
    trading/runtime/runner.py trading/risk/state.py \
    scripts/backfill_slippage.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_paper_executor.py \
    tests/unit/test_runner.py tests/unit/test_risk_state.py -v

# 4. 覆盖率（核心模块 ≥ 95%）
.venv/bin/pytest --cov=trading/execution \
    --cov=trading/runtime/runner --cov=trading/risk/state \
    --cov-fail-under=95 --cov-report=term-missing
```

**功能验证检查**：
- [ ] VA-0.1.1: `python -c "from trading.execution.paper_executor import SLIPPAGE_TIERS; print(SLIPPAGE_TIERS['BTCUSDT'])"` 输出 `5`
- [ ] VA-0.1.2: `BTCUSDT` 买入 0.01 BTC，slippage = 0.05 USDT（pytest 验证）
- [ ] VA-0.1.3: `SOLUSDT` 买入 10 SOL，slippage = 0.25 USDT（pytest 验证）
- [ ] VA-0.1.4: `grep slippage_tiers config/execution.yaml` 有输出
- [ ] VA-0.2.1: pytest `test_runner_freeze_after_3_failures` 通过
- [ ] VA-0.2.2: pytest `test_runner_unfreeze_after_timeout` 通过
- [ ] VA-0.2.3: pytest `test_runner_error_classification` 通过
- [ ] VA-0.2.4: pytest `test_runner_telegram_alert` 通过
- [ ] VA-0.2.5: pytest `test_runner_skip_frozen_symbol` 通过
- [ ] VA-0.3.1: pytest `test_consecutive_losses_symbol_isolation` 通过
- [ ] VA-0.3.2: pytest `test_consecutive_losses_win_resets_only_target` 通过
- [ ] VA-0.3.3: pytest `test_consecutive_losses_serialization` 通过
- [ ] VA-0.4.1: `python scripts/backfill_slippage.py` 返回 exit code 0
- [ ] VA-0.4.2: DB 查询 slippage > 0 的记录与 SLIPPAGE_TIERS 一致
- [ ] VA-0.4.3: `cat logs/backfill_slippage.log` 有修正记录
- [ ] VA-0.4.4: 回填脚本可重复执行（幂等）

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `SLIPPAGE_TIERS` 使用 `Decimal` 类型（非 float）
- [ ] `SLIPPAGE_TIERS` 为 class-level 常量（非函数内局部变量）
- [ ] `runner.py` 中所有异常分类有文档注释
- [ ] 时间相关逻辑使用 timezone-aware datetime
- [ ] `consecutive_losses` 为 `dict[str, int]` 类型，访问不存在的 symbol 返回 0
- [ ] `freeze_symbol` 时 `failure_counts` 被正确重置
- [ ] `backfill_slippage.py` 在事务内执行（有回滚方案）

边界情况：
- [ ] `BTCUSDT` 买入量为 0 时不触发 slippage 计算
- [ ] `ETHUSDT` 成交价为 0 时不触发 slippage 计算
- [ ] 冻结 symbol 再次收到 failure 时不重复计数
- [ ] `consecutive_losses` 序列化/反序列化后数据一致

测试充分性：
- [ ] 所有 public 方法有单元测试
- [ ] mock 了 Telegram 客户端（不真实发送消息）
- [ ] mock 了 Binance API 响应（不真实调用）

文档更新：
- [ ] `config/execution.yaml` 包含完整配置文档
- [ ] `trading/execution/paper_executor.py` 顶部 docstring 更新
- [ ] `trading/runtime/runner.py` 中 `APIFailureDegradation` 类有 docstring
- [ ] `scripts/backfill_slippage.py` 有 `--help` 和 usage 说明

风险评估：
- [ ] 无破坏性改动（现有 API 签名未变）
- [ ] 回填脚本执行前有数据备份
- [ ] `consecutive_losses` 迁移脚本兼容旧数据

---

## 四、阶段 1：退出策略 100%（1-2 周）

### T1.1: ExitConfig 数据类

**改动文件**：
- `trading/strategies/exits.py`

**实现**：
```python
@dataclass
class ExitConfig:
    hard_stop_atr_mult: Decimal = Decimal("2")
    take_profit_atr_mult: Decimal = Decimal("3")
    max_hold_hours: int = 24
    time_exit_pct: Decimal = Decimal("0.5")  # 50% 仓位

@dataclass
class ExitSignal:
    symbol: str
    reason: ExitReason  # HARD_STOP / TAKE_PROFIT / TIME_EXIT / MANUAL
    exit_price: Decimal
    qty_to_exit: Decimal  # Decimal("1.0") = 全平, Decimal("0.5") = 平50%
    created_at: datetime
    confidence: Decimal = Decimal("1.0")
    message: str = ""
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-1.1.1 | `ExitConfig(hard_stop_atr_mult=2)` 实例化正常 | pytest `test_exit_config_instantiation` |
| VA-1.1.2 | `ExitSignal(symbol="BTCUSDT", reason=ExitReason.HARD_STOP, ...)` 序列化正常 | pytest `test_exit_signal_serialization` |
| VA-1.1.3 | config/exit_rules.yaml 解析后与 dataclass 对应 | pytest `test_exit_rules_yaml_parsing` |

---

### T1.2: ExitEngine 核心逻辑

**改动文件**：
- `trading/strategies/exits.py`

**实现**：
```python
class ExitEngine:
    def __init__(self, rules: list[ExitRule], config: ExitConfig):
        self.rules = {r.kind: r for r in rules}
        self.config = config

    def should_exit(
        self, position: Position, market_price: Decimal, now: datetime
    ) -> tuple[bool, ExitSignal | None]:
        signals: list[ExitSignal] = []
        for rule in self.rules.values():
            if sig := rule.evaluate(position, market_price, now):
                signals.append(sig)
        if not signals:
            return False, None
        # 触发多个时优先: HARD_STOP > TAKE_PROFIT > TIME_EXIT
        priority = {
            ExitReason.HARD_STOP: 0,
            ExitReason.TAKE_PROFIT: 1,
            ExitReason.TIME_EXIT: 2,
        }
        best = min(signals, key=lambda s: priority[s.reason])
        return True, best

class HardStopRule:
    def evaluate(self, position, market_price, now) -> ExitSignal | None:
        atr = position.entry_atr or Decimal("100")
        stop_price = position.entry_price * (1 - self.config.hard_stop_atr_mult * atr / position.entry_price)
        if market_price <= stop_price:
            return ExitSignal(
                symbol=position.symbol,
                reason=ExitReason.HARD_STOP,
                exit_price=market_price,
                qty_to_exit=Decimal("1.0"),
                created_at=now,
                message=f"Hard stop triggered: {market_price} <= {stop_price}"
            )

class TakeProfitRule:
    def evaluate(self, position, market_price, now) -> ExitSignal | None:
        atr = position.entry_atr or Decimal("100")
        target = position.entry_price * (1 + self.config.take_profit_atr_mult * atr / position.entry_price)
        if market_price >= target:
            pct = self._calc_exit_pct(position, market_price, target)
            return ExitSignal(
                symbol=position.symbol,
                reason=ExitReason.TAKE_PROFIT,
                exit_price=market_price,
                qty_to_exit=pct,
                created_at=now,
                message=f"Take profit triggered: {market_price} >= {target}"
            )

class TimeExitRule:
    def evaluate(self, position, market_price, now) -> ExitSignal | None:
        if not position.opened_at:
            return None
        hold_hours = (now - position.opened_at).total_seconds() / 3600
        if hold_hours >= self.config.max_hold_hours:
            return ExitSignal(
                symbol=position.symbol,
                reason=ExitReason.TIME_EXIT,
                exit_price=market_price,
                qty_to_exit=Decimal(str(self.config.time_exit_pct)),  # Decimal("0.5") = 50%
                created_at=now,
                message=f"Time exit: held {hold_hours:.1f}h >= {self.config.max_hold_hours}h"
            )
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-1.2.1 | 浮亏达到 ATR×2 时触发 HARD_STOP | pytest `test_exit_engine_hard_stop_triggered` |
| VA-1.2.2 | 浮盈达到 ATR×3 时触发 TAKE_PROFIT | pytest `test_exit_engine_take_profit_triggered` |
| VA-1.2.3 | 持仓超 24h 触发 TIME_EXIT，平仓 50% | pytest `test_exit_engine_time_exit_partial` |
| VA-1.2.4 | 同时触发止损和止盈，优先执行止损 | pytest `test_exit_engine_hard_stop_priority` |
| VA-1.2.5 | 无持仓时 `should_exit` 返回 `(False, None)` | pytest `test_exit_engine_no_position` |
| VA-1.2.6 | 覆盖率 ≥ 95% | `pytest --cov=trading/strategies/exits --cov-fail-under=95` |

**代码审查清单**：
- [ ] `position.entry_atr` 为 None 时的默认 ATR 处理合理
- [ ] `exit_price` 使用 `market_price` 而非目标价（立即市价平仓）
- [ ] `qty_to_exit` 为 Decimal 类型，全程无 float

---

### T1.3: ExitEngine 串联入 paper_cycle

**改动文件**：
- `trading/runtime/paper_cycle.py`

**实现**（在现有 cycle 中添加第 10 步）：
```python
# PaperCycle.run() 内，在执行买入信号之后添加：

# --- Stage 10: Evaluate exits ---
for symbol in list(self.portfolio.positions.keys()):
    if (position := self.portfolio.get_position(symbol)) and \
       (current_price := self.market_data.get_price(symbol)):
        should_exit, exit_signal = self.exit_engine.should_exit(
            position, current_price, cycle_time
        )
        if should_exit:
            logger.info(f"Exit signal: {exit_signal.symbol} {exit_signal.reason.value}")
            exit_result = await self.paper_executor.execute_exit(exit_signal)
            await self.events_repo.record_exit(exit_signal, exit_result)
            await self.ws_manager.broadcast_signal({
                "type": "exit",
                "signal": asdict(exit_signal),
                "result": asdict(exit_result)
            })
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-1.3.1 | 持仓超过 24h 自动发出 TIME_EXIT 信号 | 集成测试 `test_paper_cycle_time_exit_integration` |
| VA-1.3.2 | ExitSignal 写入 `exit_signals` 表（阶段 2b 后） | DB 查询有记录 |
| VA-1.3.3 | WebSocket 推送 exit 信号 | WebSocket mock 测试 `test_ws_broadcast_exit` |
| VA-1.3.4 | 部分退出后持仓数量正确更新 | pytest `test_partial_exit_position_update` |
| VA-1.3.5 | 集成测试完整流程（买入→持有→部分退出→全平）| pytest `test_exit_flow_full_cycle` |

---

### T1.4: ExitConfig YAML 配置

**改动文件**：
- `config/exit_rules.yaml`（新建）

**实现**：
```yaml
exit_rules:
  hard_stop:
    atr_multiplier: 2.0
  take_profit:
    atr_multiplier: 3.0
  time_exit:
    max_hold_hours: 24
    partial_exit_pct: 0.5
  trailing_stop:  # 预留，未来扩展
    enabled: false
    activation_profit_pct: 0.05
    trail_distance_pct: 0.02
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-1.4.1 | YAML 解析后所有数值类型正确（无 str） | pytest `test_exit_rules_yaml_types` |
| VA-1.4.2 | 策略运行时读取 YAML 覆盖默认值 | pytest `test_exit_rules_yaml_override` |
| VA-1.4.3 | 缺少字段时有合理默认值（不抛异常） | pytest `test_exit_rules_yaml_missing_field` |

### Stage 1 Review Checklist（退出策略）

**PR 标题格式**：`[Stage-1] 退出策略 100%`

**前置依赖**：Stage 0 Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/strategies/exits.py \
    trading/runtime/paper_cycle.py

# 2. 代码风格
.venv/bin/ruff check trading/strategies/exits.py \
    trading/runtime/paper_cycle.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_exit_engine.py \
    tests/unit/test_exit_rules.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_exit_flow_full_cycle.py -v

# 5. 覆盖率（核心模块 ≥ 95%）
.venv/bin/pytest --cov=trading/strategies/exits \
    --cov=trading/runtime/paper_cycle \
    --cov-fail-under=95 --cov-report=term-missing
```

**功能验证检查**：
- [ ] VA-1.1.1: pytest `test_exit_config_instantiation` 通过
- [ ] VA-1.1.2: pytest `test_exit_signal_serialization` 通过
- [ ] VA-1.1.3: pytest `test_exit_rules_yaml_parsing` 通过
- [ ] VA-1.2.1: pytest `test_exit_engine_hard_stop_triggered` 通过
- [ ] VA-1.2.2: pytest `test_exit_engine_take_profit_triggered` 通过
- [ ] VA-1.2.3: pytest `test_exit_engine_time_exit_partial` 通过
- [ ] VA-1.2.4: pytest `test_exit_engine_hard_stop_priority` 通过
- [ ] VA-1.2.5: pytest `test_exit_engine_no_position` 通过
- [ ] VA-1.3.1: pytest `test_paper_cycle_time_exit_integration` 通过
- [ ] VA-1.3.2: DB 查询 exit_signals 表有记录（Stage 2b 完成后验证）
- [ ] VA-1.3.3: pytest `test_ws_broadcast_exit` 通过
- [ ] VA-1.3.4: pytest `test_partial_exit_position_update` 通过
- [ ] VA-1.3.5: pytest `test_exit_flow_full_cycle` 通过
- [ ] VA-1.4.1: pytest `test_exit_rules_yaml_types` 通过
- [ ] VA-1.4.2: pytest `test_exit_rules_yaml_override` 通过
- [ ] VA-1.4.3: pytest `test_exit_rules_yaml_missing_field` 通过

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `ExitSignal.exit_price` 使用 `market_price`（立即市价平仓），非目标价
- [ ] `position.entry_atr` 为 `None` 时有合理的默认 ATR 处理
- [ ] `qty_to_exit` 为 `Decimal` 类型，全程无 float 混用
- [ ] 止损优先级高于止盈：`HARD_STOP(0) < TAKE_PROFIT(1) < TIME_EXIT(2)`
- [ ] `TimeExitRule` 部分退出后，`position.opened_at` 不重置（继续计时）
- [ ] `ExitEngine.should_exit` 在无持仓时返回 `(False, None)`
- [ ] `paper_cycle.py` 中 ExitEngine 调用处无任何 bypass 路径

边界情况：
- [ ] 持仓刚好 24h（`== 24.0h`）时触发 TIME_EXIT
- [ ] 持仓刚超过 24h（`> 24.0h`）时只退出 50%，不全部平仓
- [ ] `atr = 0` 时（不应该发生）默认 ATR 处理合理
- [ ] YAML 中 `atr_multiplier` 缺失字段时使用默认值

测试充分性：
- [ ] ExitEngine 每个 ExitRule 有独立的单元测试
- [ ] ExitEngine 多规则同时触发时有优先级测试
- [ ] ExitEngine 串联集成测试覆盖完整 cycle

文档更新：
- [ ] `config/exit_rules.yaml` 有完整配置注释
- [ ] `trading/strategies/exits.py` 顶部模块 docstring 更新
- [ ] `ExitSignal` dataclass 有字段说明 docstring

风险评估：
- [ ] 无破坏性改动（现有 API 签名未变）
- [ ] 退出逻辑变更不影响风控（PreFlightCheck）
- [ ] 部分退出（50%）逻辑在 Portfolio 中正确处理

---

## 五、阶段 2：回测框架 + 因子库（3-4 周）

### T2.1: Parquet 数据存储架构

**改动文件**：
- `trading/backtest/data_loader.py`（新建）
- `backtest_data/`（目录新建）

**实现**：
```python
from pyarrow import parquet as pq
from pathlib import Path

class ParquetCandleStore:
    def __init__(self, data_dir: Path = Path("backtest_data/candles")):
        self.data_dir = data_dir

    def save(self, symbol: str, timeframe: str, df: pd.DataFrame):
        path = self.data_dir / f"{symbol.lower()}_{timeframe}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression="snappy")

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame:
        path = self.data_dir / f"{symbol.lower()}_{timeframe}.parquet"
        return pd.read_parquet(path)

    def exists(self, symbol: str, timeframe: str) -> bool:
        path = self.data_dir / f"{symbol.lower()}_{timeframe}.parquet"
        return path.exists()
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-2.1.1 | 1000 条 BTCUSDT 15m 数据保存为 Parquet 后文件大小 < 1MB | `ls -lh backtest_data/candles/btcusdt_15m.parquet` |
| VA-2.1.2 | 保存后读取 DataFrame 与原始数据一致（`df.equals()`）| pytest `test_parquet_roundtrip` |
| VA-2.1.3 | 读取不存在的文件返回空 DataFrame（不抛异常）| pytest `test_parquet_load_missing` |
| VA-2.1.4 | Parquet 文件可用 `parquet-tools` 读取 | `parquet-tools inspect backtest_data/candles/btcusdt_15m.parquet` |

---

### T2.2: BinanceHistoricalLoader

**改动文件**：
- `trading/backtest/data_loader.py`

**实现**：
```python
class BinanceHistoricalLoader:
    BASE_URL = "https://api.binance.com/api/v3"

    async def download_candles(
        self,
        symbol: str,
        interval: str,  # "15m" / "1h" / "4h"
        start_time: datetime,
        end_time: datetime,
    ) -> pd.DataFrame:
        rows = []
        current = start_time
        while current < end_time:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": int(current.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 1000,
            }
            resp = await self._get("/klines", params)
            for k in resp:
                rows.append({
                    "open_time": pd.to_datetime(k[0], unit="ms"),
                    "open": Decimal(k[1]),
                    "high": Decimal(k[2]),
                    "low": Decimal(k[3]),
                    "close": Decimal(k[4]),
                    "volume": Decimal(k[5]),
                    "close_time": pd.to_datetime(k[6], unit="ms"),
                })
            current = pd.to_datetime(rows[-1]["close_time"]) + timedelta(minutes=1)
        return pd.DataFrame(rows)
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-2.2.1 | 下载 2023-01-01 至 2023-01-07 的 BTCUSDT 15m 数据，条数 = 7×96=672 | pytest `test_binance_loader_week_data` |
| VA-2.2.2 | OHLC 数值类型全程为 Decimal（无 float）| pytest `test_binance_loader_decimal_type` |
| VA-2.2.3 | API 限流时自动重试 3 次 | mock 429 响应后验证重试次数 |
| VA-2.2.4 | 下载后自动保存为 Parquet | 验证 `backtest_data/candles/btcusdt_15m.parquet` 存在 |

---

### T2.3: BacktestEngine 核心

**改动文件**：
- `trading/backtest/engine.py`（新建）
- `trading/backtest/config.py`（新建）

**实现**：
```python
@dataclass
class BacktestConfig:
    fee_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("20")
    slippage_tiers: dict[str, Decimal] = field(default_factory=dict)
    max_position_pct: Decimal = Decimal("20")
    risk_profile: str = "small_balanced"
    exit_config: ExitConfig = field(default_factory=ExitConfig)

@dataclass
class BacktestResult:
    strategy_name: str
    symbols: list[str]
    start_time: datetime
    end_time: datetime
    initial_equity: Decimal
    final_equity: Decimal
    total_return_pct: Decimal
    sharpe_ratio: float
    max_drawdown_pct: Decimal
    win_rate: Decimal
    avg_win_loss_ratio: Decimal
    total_trades: int
    monthly_returns: dict[str, Decimal]  # "2023-01": Decimal("0.05")
    equity_curve: list[tuple[datetime, Decimal]]

class BacktestEngine:
    def __init__(self, config: BacktestConfig, store: ParquetCandleStore):
        self.config = config
        self.store = store

    def run(
        self,
        strategy: Strategy,
        symbols: list[str],
        start_time: datetime,
        end_time: datetime,
        initial_equity: Decimal,
    ) -> BacktestResult:
        # 1. 加载数据
        data = {sym: self.store.load(sym, "15m") for sym in symbols}
        # 2. 初始化资金
        equity = initial_equity
        positions: dict[str, Position] = {}
        equity_curve = []
        # 3. 按时间迭代
        for dt in self._iter_dates(start_time, end_time):
            # ... 策略信号 → 风控 → 执行 → 更新持仓
            equity_curve.append((dt, equity))
        # 4. 计算指标
        return BacktestResult(...)
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-2.3.1 | 2023-01 to 2023-03 BTCUSDT momentum 策略跑出结果（非 NaN）| pytest `test_backtest_engine_runs_without_nan` |
| VA-2.3.2 | 夏普比率计算正确（手算验证） | 用已知数据的子集运行，比对输出 |
| VA-2.3.3 | 最大回撤计算正确（找到权益曲线最低点）| pytest `test_backtest_engine_max_drawdown` |
| VA-2.3.4 | 资金曲线从 initial_equity 开始 | assert equity_curve[0] == initial_equity |
| VA-2.3.5 | 交易次数统计正确 | 有交易时 total_trades > 0 |
| VA-2.3.6 | 覆盖率 ≥ 85% | `pytest --cov=trading/backtest/engine --cov-fail-under=85` |

---

### T2.4-T2.7: 因子库（9个新因子）

**改动文件**：
- `trading/features/momentum.py`（新建）
- `trading/features/volatility.py`（新建）
- `trading/features/volume.py`（新建）
- `trading/features/trend.py`（新建）

**新因子清单**：

| # | 因子名 | 文件 | 函数签名 |
|---|--------|------|---------|
| F1 | MACD | momentum.py | `def macd(closes: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame` |
| F2 | ROC | momentum.py | `def roc(closes: pd.Series, period=12) -> pd.Series` |
| F3 | CCI | momentum.py | `def cci(high, low, close, period=20) -> pd.Series` |
| F4 | Stochastic | momentum.py | `def stochastic(high, low, close, k=14, d=3) -> pd.DataFrame` |
| F5 | Bollinger Bands | volatility.py | `def bollinger_bands(closes: pd.Series, period=20, std=2) -> pd.DataFrame` |
| F6 | Keltner Channel | volatility.py | `def keltner_channel(high, low, close, ema_period=20, atr_period=10, mult=2) -> pd.DataFrame` |
| F7 | OBV | volume.py | `def obv(closes: pd.Series, volumes: pd.Series) -> pd.Series` |
| F8 | VWAP | volume.py | `def vwap(high, low, close, volumes: pd.Series) -> pd.Series` |
| F9 | ADX | trend.py | `def adx(high, low, close, period=14) -> pd.Series` |
| F10 | Supertrend | trend.py | `def supertrend(high, low, close, period=10, mult=3) -> pd.DataFrame` |
| F11 | Aroon | trend.py | `def aroon(high, low, period=25) -> pd.DataFrame` |

**验收标准**（每个因子）：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-Fx.1 | 函数输出形状与输入相同（无数据丢失）| `len(output) == len(input)` |
| VA-Fx.2 | NaN 值数量符合预期（前 N 个为 NaN）| 验证前 `period` 个值为 NaN |
| VA-Fx.3 | MACD: signal 线 = MACD 线的 EMA-9 | 与 ta-lib 对比误差 < 1e-6 |
| VA-Fx.4 | Bollinger Bands: 中轨 = SMA-20，上下轨 = 中轨 ± 2σ | 与 ta-lib 对比误差 < 1e-6 |
| VA-Fx.5 | 数值类型全程 Decimal 或 float（无混用）| type hint 正确 |
| VA-Fx.6 | 覆盖率 ≥ 85% | `pytest --cov=trading/features --cov-fail-under=85` |

### Stage 2 Review Checklist（回测框架 + 因子库）

**PR 标题格式**：`[Stage-2] 回测框架 + 因子库`

**前置依赖**：Stage 0 + Stage 1 Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/backtest/ trading/features/

# 2. 代码风格
.venv/bin/ruff check trading/backtest/ trading/features/

# 3. 单元测试
.venv/bin/pytest tests/unit/test_backtest_engine.py \
    tests/unit/test_indicators.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_backtest_integration.py -v

# 5. 覆盖率（回测 ≥ 85%，因子库 ≥ 85%）
.venv/bin/pytest --cov=trading/backtest \
    --cov=trading/features \
    --cov-fail-under=85 --cov-report=term-missing
```

**功能验证检查**：
- [ ] VA-2.1.1: Parquet 文件 < 1MB（`ls -lh backtest_data/candles/btcusdt_15m.parquet`）
- [ ] VA-2.1.2: pytest `test_parquet_roundtrip` 通过
- [ ] VA-2.1.3: pytest `test_parquet_load_missing` 通过
- [ ] VA-2.2.1: 下载 7 天 BTCUSDT 15m 数据条数 = 672（`len(df) == 672`）
- [ ] VA-2.2.2: pytest `test_binance_loader_decimal_type` 通过
- [ ] VA-2.2.3: API 限流时自动重试 3 次（mock 验证）
- [ ] VA-2.2.4: Parquet 文件保存成功（文件存在）
- [ ] VA-2.3.1: pytest `test_backtest_engine_runs_without_nan` 通过
- [ ] VA-2.3.2: 夏普比率手算验证误差 < 0.01
- [ ] VA-2.3.3: pytest `test_backtest_engine_max_drawdown` 通过
- [ ] VA-2.3.4: `equity_curve[0] == initial_equity` 断言通过
- [ ] VA-2.3.5: 有交易时 `total_trades > 0`
- [ ] VA-F1.1 ~ VA-F11.6: 11 个因子函数全部通过 pytest

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `BinanceHistoricalLoader` 使用 `Decimal` 类型存储 OHLC（非 float）
- [ ] `BacktestEngine.run()` 在 `end_time` 之后正确终止循环
- [ ] `BacktestConfig.slippages` 按 symbol 分级（不同 symbol 不同 slippage）
- [ ] `fee_bps` 在每次交易时被正确扣除（买入扣一次，卖出扣一次）
- [ ] 因子函数（MACD/BB 等）对输入 `NaN` 值有正确处理（返回对应 NaN）
- [ ] `ParquetCandleStore` 的 `save()` 使用 `compression="snappy"`

边界情况：
- [ ] 尝试加载不存在的 Parquet 文件返回空 DataFrame（不抛异常）
- [ ] 下载数据时网络中断，重试 3 次后仍失败时抛出 `RuntimeError`
- [ ] 历史数据区间不足（< 100 条）时回测引擎返回错误而非 NaN
- [ ] 因子计算时 `period > len(df)` 时返回全 NaN（不抛异常）

测试充分性：
- [ ] 每个因子函数有独立的单元测试
- [ ] `BacktestEngine` 有已知结果的端到端测试（固定 seed 数据）
- [ ] `BinanceHistoricalLoader` 有 mock HTTP 响应测试

文档更新：
- [ ] `trading/backtest/engine.py` 顶部有 `BacktestEngine` 和 `BacktestResult` 的模块 docstring
- [ ] `BacktestConfig` dataclass 每个字段有 docstring
- [ ] `config/exit_rules.yaml` 中的回测参数说明存在
- [ ] 每个因子函数有 docstring 说明参数含义

风险评估：
- [ ] 回测引擎不对外发送任何网络请求（仅读取 Parquet）
- [ ] `scripts/` 下无敏感信息（API key 等）
- [ ] Parquet 目录不存在时 `BinanceHistoricalLoader` 自动创建

---

## 六、阶段 2b：数据迁移 + Schema 扩展

### T2b.1-T2b.6: 新增数据库表

**改动文件**：
- `trading/storage/models.py`
- `trading/storage/db.py`
- `scripts/migrate_stage2b.py`（新建）

**新表清单**：

```sql
-- exit_signals 表
CREATE TABLE exit_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('HARD_STOP', 'TAKE_PROFIT', 'TIME_EXIT', 'MANUAL')),
    exit_price REAL NOT NULL,
    qty_to_exit REAL NOT NULL CHECK(qty_to_exit > 0 AND qty_to_exit <= 1),
    pnl_realized REAL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cycle_id, symbol)
);

-- ai_scores 表
CREATE TABLE ai_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ai_score REAL NOT NULL CHECK(ai_score >= 0 AND ai_score <= 1),
    decision TEXT NOT NULL CHECK(decision IN ('buy', 'reject', 'hold', 'sell')),
    confidence REAL CHECK(confidence >= 0 AND confidence <= 1),
    risk_level TEXT CHECK(risk_level IN ('low', 'medium', 'high')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- backtest_runs 表
CREATE TABLE backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbols TEXT NOT NULL,  -- JSON array: ["BTCUSDT", "ETHUSDT"]
    start_time TEXT NOT NULL,  -- ISO format
    end_time TEXT NOT NULL,
    initial_equity REAL NOT NULL,
    final_equity REAL NOT NULL,
    sharpe_ratio REAL,
    max_drawdown_pct REAL,
    win_rate REAL,
    avg_win_loss_ratio REAL,
    total_trades INTEGER,
    result_json TEXT NOT NULL,  -- Full result as JSON
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- strategy_params_history 表
CREATE TABLE strategy_params_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    param_key TEXT NOT NULL,
    param_value TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL,  -- ISO format
    reason TEXT,
    UNIQUE(strategy_name, param_key, changed_at)
);

-- risk_states 表修改
ALTER TABLE risk_states 
ADD COLUMN consecutive_losses_json TEXT NOT NULL DEFAULT '{}';
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-2b.1 | 所有新表创建成功，无重复列名 | `sqlite3 data/crypto_ai_trader.sqlite3 ".tables"` 列出新表 |
| VA-2b.2 | CHECK 约束有效（写入非法值被拒绝）| pytest `test_db_check_constraints` |
| VA-2b.3 | UNIQUE 约束有效（重复插入被拒绝）| pytest `test_db_unique_constraints` |
| VA-2b.4 | 迁移脚本可重复执行（幂等）| 运行两次第二次为 no-op |
| VA-2b.5 | 迁移前有备份（`data/backup_pre_2b/`）| `ls data/backup_pre_2b/` 有文件 |
| VA-2b.6 | 迁移后所有现有功能无回归 | `pytest tests/ -x -q` 全绿 |
| VA-2b.7 | risk_states.consecutive_losses_json 读写正常 | pytest `test_risk_state_json_serialization` |

**代码审查清单**：
- [ ] 迁移脚本有 dry-run 模式（不实际修改）
- [ ] 所有 ALTER TABLE 在事务内
- [ ] 迁移失败时有回滚
- [ ] 新增字段有 DEFAULT 值（不影响现有行）

### Stage 2b Review Checklist（数据迁移 + Schema 扩展）

**PR 标题格式**：`[Stage-2b] 数据迁移 + Schema 扩展`

**前置依赖**：Stage 2 Review Checklist 全部通过（或与 Stage 2 并行）

**自动化检查**：
```bash
# 1. 类型检查（新建的 model 文件）
.venv/bin/mypy --strict trading/storage/models.py

# 2. 代码风格
.venv/bin/ruff check trading/storage/models.py \
    scripts/migrate_stage2b.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_storage_models.py \
    tests/unit/test_db_migrations.py -v

# 4. 迁移测试
.venv/bin/python scripts/migrate_stage2b.py --dry-run
.venv/bin/python scripts/migrate_stage2b.py  # 实际执行
.venv/bin/pytest tests/integration/test_db_schema.py -v
```

**功能验证检查**：
- [ ] VA-2b.1: `sqlite3 data/crypto_ai_trader.sqlite3 ".tables"` 列出新表（exit_signals / ai_scores / backtest_runs / strategy_params_history）
- [ ] VA-2b.2: pytest `test_db_check_constraints` 通过
- [ ] VA-2b.3: pytest `test_db_unique_constraints` 通过
- [ ] VA-2b.4: 迁移脚本运行两次第二次为 no-op（幂等）
- [ ] VA-2b.5: `ls data/backup_pre_2b/` 有备份文件
- [ ] VA-2b.6: `pytest tests/ -x -q` 全绿（无回归）
- [ ] VA-2b.7: pytest `test_risk_state_json_serialization` 通过

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `scripts/migrate_stage2b.py` 在事务内执行所有 ALTER TABLE
- [ ] 迁移脚本有 `--dry-run` 模式（只读预览，不修改 DB）
- [ ] 迁移脚本在执行前自动备份到 `data/backup_pre_2b/`
- [ ] `risk_states.consecutive_losses_json` 的 `DEFAULT` 值为 `'{}'`（空 dict JSON）
- [ ] `exit_signals.qty_to_exit` 的 CHECK 约束为 `> 0 AND <= 1`

边界情况：
- [ ] 迁移到已有 DB 时（不是空白 DB），`SELECT COUNT(*) FROM exit_signals` 不报错
- [ ] 重复运行迁移脚本不报错（幂等性）
- [ ] 迁移失败时有回滚（Transaction ROLLBACK）
- [ ] DB 文件被占用时迁移脚本给出友好错误

测试充分性：
- [ ] 有针对 CHECK 约束的测试（写入非法值被拒绝）
- [ ] 有针对 UNIQUE 约束的测试（重复插入被拒绝）
- [ ] 有针对迁移回滚的测试

文档更新：
- [ ] `scripts/migrate_stage2b.py` 有 `--help` 说明
- [ ] `docs/` 下有迁移说明文档（新建 `docs/migrations/stage-2b.md`）

风险评估：
- [ ] 备份文件存在且可读取
- [ ] 迁移脚本不删除任何现有列（只 ADD COLUMN）
- [ ] 回滚脚本 `scripts/rollback_stage2b.py` 存在且可执行

---

## 七、阶段 5.1-5.2：风控链路 100%

### T5.1: PreFlightCheck 强制执行链路

**改动文件**：
- `trading/risk/pre_flight.py`

**实现**：
```python
@dataclass
class PreFlightDecision:
    approved: bool
    reason: str
    rejected_by: str | None = None  # 用于诊断

class PreFlightCheck:
    def verify_position_acceptable(
        self,
        symbol: str,
        proposed_qty: Decimal,
        current_price: Decimal,
        portfolio: PortfolioAccount,
        risk_state: RiskState,
    ) -> PreFlightDecision:
        proposed_value = proposed_qty * current_price
        proposed_pct = proposed_value / portfolio.total_equity * 100

        # Check 1: 保证金充足
        if proposed_value > portfolio.available_margin:
            return PreFlightDecision(False, f"Margin insufficient", rejected_by="margin")

        # Check 2: 单 symbol 最大仓位
        if proposed_pct > Decimal("20"):
            return PreFlightDecision(False, f"单币仓位超 20%", rejected_by="max_position_per_symbol")

        # Check 3: 总暴露
        total_exposure = sum(
            (pos.qty * self.market_data.get_price(pos.symbol)) 
            for pos in portfolio.positions.values()
        )
        exposure_pct = (total_exposure + proposed_value) / portfolio.total_equity * 100
        if exposure_pct > Decimal("60"):
            return PreFlightDecision(False, f"总敞口超 60%", rejected_by="total_exposure")

        # Check 4: 每日亏损限制
        if portfolio.daily_pnl < -(portfolio.total_equity * Decimal("0.02")):
            return PreFlightDecision(False, f"单日亏损超 2%", rejected_by="daily_loss_limit")

        # Check 5: Symbol 冻结
        if risk_state.is_symbol_frozen(symbol):
            return PreFlightDecision(False, f"Symbol frozen", rejected_by="frozen_symbol")

        return PreFlightDecision(True, "Approved")

# 使用处（paper_cycle.py 中调用，无 bypass）
decision = pre_flight.verify_position_acceptable(...)
if not decision.approved:
    logger.warning(f"PreFlight rejected {symbol}: {decision.reason}")
    continue  # 直接跳过，不创建 order
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-5.1.1 | 保证金不足时返回 `approved=False, rejected_by="margin"` | pytest `test_preflight_margin_rejection` |
| VA-5.1.2 | 单币仓位 > 20% 时返回 `approved=False, rejected_by="max_position"` | pytest `test_preflight_max_position_rejection` |
| VA-5.1.3 | 总敞口 > 60% 时返回 `approved=False, rejected_by="total_exposure"` | pytest `test_preflight_total_exposure_rejection` |
| VA-5.1.4 | 每日亏损 > 2% 时返回 `approved=False, rejected_by="daily_loss"` | pytest `test_preflight_daily_loss_rejection` |
| VA-5.1.5 | 冻结 symbol 返回 `approved=False, rejected_by="frozen"` | pytest `test_preflight_frozen_rejection` |
| VA-5.1.6 | 所有检查通过时返回 `approved=True` | pytest `test_preflight_approval` |
| VA-5.1.7 | **无任何 bypass 路径**（代码审查） | 人工审查 `paper_cycle.py` 中调用处 |
| VA-5.1.8 | 覆盖率 ≥ 95% | `pytest --cov=trading/risk/pre_flight --cov-fail-under=95` |

---

### T5.2: PostTrade PositionMonitor

**改动文件**：
- `trading/risk/position_monitor.py`（新建）

**实现**：
```python
class PositionMonitor:
    def check_market_exposure(
        self, symbol: str, current_price: Decimal, position: Position
    ) -> list[Alert]:
        alerts = []
        # VaR check (95%, 1-day, 假设 σ = 2 * daily_atr)
        var_95 = position.current_value * Decimal("0.02")  # 简化: 2% VaR
        if position.unrealized_pnl < -var_95:
            alerts.append(Alert(
                level=AlertLevel.WARNING,
                msg=f"VaR breach {symbol}: PnL={position.unrealized_pnl} < -VaR={var_95}"
            ))
        # 持仓时间超限
        hold_hours = (datetime.now() - position.opened_at).total_seconds() / 3600
        if hold_hours > 20:  # 80% of max_hold_hours
            alerts.append(Alert(
                level=AlertLevel.INFO,
                msg=f"Position aging {symbol}: {hold_hours:.1f}h"
            ))
        return alerts

    def check_correlation_risk(self, positions: dict[str, Position]) -> list[Alert]:
        # 简化为: 超过 3 个同向持仓则告警
        bullish = [s for s, p in positions.items() if p.side == "LONG"]
        if len(bullish) > 3:
            return [Alert(level=AlertLevel.WARNING,
                         msg=f"High correlation risk: {len(bullish)} long positions")]
        return []
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-5.2.1 | VaR 突破时触发 WARNING 告警 | pytest `test_position_monitor_var_alert` |
| VA-5.2.2 | 持仓超 20h 时触发 INFO 告警 | pytest `test_position_monitor_age_alert` |
| VA-5.2.3 | 超过 3 个同向持仓触发 WARNING | pytest `test_position_monitor_correlation_alert` |
| VA-5.2.4 | 无持仓时告警列表为空（不抛异常）| pytest `test_position_monitor_empty_portfolio` |
| VA-5.2.5 | 覆盖率 ≥ 90% | `pytest --cov=trading/risk/position_monitor --cov-fail-under=90` |

---

### T5.5: AI ScoreValidator

**改动文件**：
- `trading/ai/score_validator.py`（新建）

**实现**：
```python
@dataclass
class ValidationResult:
    min_score_threshold: float
    total_signals: int
    winning_signals: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy: float  # (win_rate * avg_win) - (loss_rate * avg_loss)
    auc: float | None

class ScoreValidator:
    def validate_score_threshold(
        self,
        historical_signals: list[SignalWithOutcome],  # {score, decision, pnl_pct}
        thresholds: list[float] = [0.5, 0.55, 0.6, 0.65, 0.7],
    ) -> dict[float, ValidationResult]:
        results = {}
        for threshold in thresholds:
            subset = [s for s in historical_signals if s.score >= threshold]
            wins = [s for s in subset if s.pnl_pct > 0]
            losses = [s for s in subset if s.pnl_pct <= 0]
            results[threshold] = ValidationResult(
                min_score_threshold=threshold,
                total_signals=len(subset),
                winning_signals=len(wins),
                win_rate=len(wins)/len(subset) if subset else 0,
                avg_win_pct=statistics.mean([s.pnl_pct for s in wins]) if wins else 0,
                avg_loss_pct=abs(statistics.mean([s.pnl_pct for s in losses])) if losses else 0,
                expectancy=...,
                auc=None,  # 简化版本不含 AUC
            )
        return results

    def find_optimal_threshold(self, results: dict[float, ValidationResult]) -> float:
        """找到期望收益最高的阈值"""
        return max(results, key=lambda t: results[t].expectancy)
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-5.5.1 | 0.6 阈值下胜率 > 0.5 时 expectency > 0 | 用模拟数据验证 |
| VA-5.5.2 | 0.7 阈值的 total_signals < 0.6 阈值的 | 验证筛选严格性 |
| VA-5.5.3 | 空信号列表返回空 dict（不抛异常）| pytest `test_score_validator_empty` |
| VA-5.5.4 | find_optimal_threshold 返回 expectency 最高的阈值 | pytest `test_score_validator_optimal` |
| VA-5.5.5 | 输出写入 backtest_runs 表（JSON 格式）| DB 验证 |

### Stage 5 Review Checklist（风控链路 100%）

**PR 标题格式**：`[Stage-5] 风控链路 100%`

**前置依赖**：Stage 2 + Stage 2b Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/risk/pre_flight.py \
    trading/risk/position_monitor.py trading/ai/score_validator.py

# 2. 代码风格
.venv/bin/ruff check trading/risk/pre_flight.py \
    trading/risk/position_monitor.py trading/ai/score_validator.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_pre_flight.py \
    tests/unit/test_position_monitor.py \
    tests/unit/test_score_validator.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_risk_chain_integration.py -v

# 5. 覆盖率（风控 ≥ 95%，AI ≥ 85%）
.venv/bin/pytest --cov=trading/risk/pre_flight \
    --cov=trading/risk/position_monitor \
    --cov=trading/ai/score_validator \
    --cov-fail-under=95 --cov-report=term-missing
```

**功能验证检查**：
- [ ] VA-5.1.1: pytest `test_preflight_margin_rejection` 通过
- [ ] VA-5.1.2: pytest `test_preflight_max_position_rejection` 通过
- [ ] VA-5.1.3: pytest `test_preflight_total_exposure_rejection` 通过
- [ ] VA-5.1.4: pytest `test_preflight_daily_loss_rejection` 通过
- [ ] VA-5.1.5: pytest `test_preflight_frozen_rejection` 通过
- [ ] VA-5.1.6: pytest `test_preflight_approval` 通过
- [ ] VA-5.1.7: `paper_cycle.py` 中 PreFlightCheck 调用处无任何 bypass 路径（代码审查）
- [ ] VA-5.2.1: pytest `test_position_monitor_var_alert` 通过
- [ ] VA-5.2.2: pytest `test_position_monitor_age_alert` 通过
- [ ] VA-5.2.3: pytest `test_position_monitor_correlation_alert` 通过
- [ ] VA-5.2.4: pytest `test_position_monitor_empty_portfolio` 通过
- [ ] VA-5.5.1: pytest `test_score_validator_threshold` 通过
- [ ] VA-5.5.2: pytest `test_score_validator_stricter_threshold` 通过
- [ ] VA-5.5.3: pytest `test_score_validator_empty` 通过
- [ ] VA-5.5.4: pytest `test_score_validator_optimal` 通过
- [ ] VA-5.5.5: DB 中 backtest_runs 表有 ScoreValidator 输出记录

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `PreFlightCheck.verify_position_acceptable()` 所有 5 项检查都有明确注释
- [ ] `PreFlightDecision.rejected_by` 字段正确标识拒绝原因（用于诊断）
- [ ] `PreFlightCheck` 在 `paper_cycle.py` 中被调用，无任何 bypass 变量（如 `if os.getenv("SKIP_PREFLIGHT")`）
- [ ] `VaR` 计算使用 95% 置信度、1 天持有期
- [ ] `ScoreValidator.validate_score_threshold()` 返回的 `expectancy` 计算正确：`win_rate * avg_win - loss_rate * avg_loss`
- [ ] `position_monitor.py` 中的告警不在持仓为 0 时抛异常

边界情况：
- [ ] `portfolio.total_equity == 0` 时（不应该发生）PreFlight 有合理处理
- [ ] `current_price == 0` 时（不应该发生）不触发计算
- [ ] `ScoreValidator` 输入列表为空时返回空 dict（不抛异常）
- [ ] `position_monitor` 在无持仓时返回空告警列表（不抛异常）

测试充分性：
- [ ] `PreFlightCheck` 有每个 `rejected_by` 场景的独立测试
- [ ] `PositionMonitor` 有多持仓场景的集成测试
- [ ] `ScoreValidator` 有已知结果的模拟数据测试

文档更新：
- [ ] `trading/risk/pre_flight.py` 有 `PreFlightDecision` 的 docstring
- [ ] `trading/risk/position_monitor.py` 有 `PositionMonitor` 的模块 docstring
- [ ] `config/risk_limits.yaml`（如新建）有风控阈值配置说明

风险评估：
- [ ] 风控链路上无 `TODO` 或 `FIXME`（必须全部解决）
- [ ] 无任何 hardcoded 风控阈值（必须来自配置文件）
- [ ] 紧急情况下有 `emergency_reject_all` 路径（不需要 AI）

---

## 八、阶段 3：策略多元化

### T3.2: Mean Reversion 策略

**改动文件**：
- `trading/strategies/active/mean_reversion.py`（新建）

**实现**：
```python
class MeanReversionStrategy(Strategy):
    def __init__(self, config: MeanReversionConfig):
        self.config = config

    def generate_signals(self, symbol: str, candles_15m, candles_1h) -> list[Signal]:
        df = candles_15m.copy()
        closes = df["close"]
        bb = bollinger_bands(closes, period=self.config.bb_period, std=self.config.bb_std)
        rsi = rsi(closes, period=self.config.rsi_period)
        
        # 信号逻辑
        signals = []
        for i in range(max(self.config.bb_period, self.config.rsi_period), len(df)):
            row = df.iloc[i]
            # 买入: 价格下穿下轨 AND RSI < 30
            if (row["close"] <= bb["lower"].iloc[i] and 
                rsi.iloc[i] < 30):
                signals.append(Signal(
                    symbol=symbol,
                    action="buy",
                    confidence=Decimal("0.7"),
                    reason=f"BB lower breach + RSI={rsi.iloc[i]:.1f}<30"
                ))
            # 卖出: 价格上穿上轨 AND RSI > 70
            elif (row["close"] >= bb["upper"].iloc[i] and 
                  rsi.iloc[i] > 70):
                signals.append(Signal(...))
        return signals
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-3.2.1 | 在 2023 年均值回归行情中产生信号 | 用 2023-05 to 2023-08 数据回测 |
| VA-3.2.2 | 参数可配置（BB_period / RSI_period / BB_std）| 修改 config 后重新运行 |
| VA-3.2.3 | 在 BacktestEngine 上运行并输出有效结果 | pytest `test_mean_reversion_backtest` |
| VA-3.2.4 | 策略注册表可正常注册和获取 | pytest `test_mean_reversion_registry` |
| VA-3.2.5 | 覆盖率 ≥ 85% | `pytest --cov=trading/strategies/active/mean_reversion --cov-fail-under=85` |

---

### T3.3: Breakout 策略

**改动文件**：
- `trading/strategies/active/breakout.py`（新建）

**实现**：
```python
class BreakoutStrategy(Strategy):
    def generate_signals(self, symbol, candles_15m, candles_1h) -> list[Signal]:
        df = candles_15m.copy()
        # Donchian Channel: N 日高低点
        period = self.config.donchian_period
        df["donchian_high"] = df["high"].rolling(period).max().shift(1)
        df["donchian_low"] = df["low"].rolling(period).min().shift(1)
        # Volume spike
        df["vol_sma"] = df["volume"].rolling(20).mean()
        # Signals
        signals = []
        for i in range(period + 1, len(df)):
            if df["close"].iloc[i] > df["donchian_high"].iloc[i] and \
               df["volume"].iloc[i] > 1.5 * df["vol_sma"].iloc[i]:
                signals.append(Signal(symbol=symbol, action="buy", confidence=Decimal("0.75"), ...))
        return signals
```

**验收标准**：
（同上 T3.2 格式）

---

### T3.6: MarketRegimeDetector

**改动文件**：
- `trading/strategies/market_regime.py`（新建）

**实现**：
```python
def detect_regime(candles_4h) -> Literal["trend", "range", "breakout"]:
    adx_val = adx(candles_4h["high"], candles_4h["low"], candles_4h["close"]).iloc[-1]
    # ADX > 25 表示趋势市场
    if adx_val > 25:
        return "trend"
    # 布林带宽度 < 历史 20% 分位数表示震荡
    bb_width = bollinger_bands(candles_4h["close"])["upper"] - \
                bollinger_bands(candles_4h["close"])["lower"]
    width_pct = (bb_width.iloc[-1] / candles_4h["close"].iloc[-1]) * 100
    if width_pct < 2:  # < 2% 布林带宽/价格 → 震荡
        return "range"
    return "breakout"
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-3.6.1 | 2023-01 BTC 趋势行情识别为 "trend" | 手动验证 |
| VA-3.6.2 | 2023-05 BTC 震荡行情识别为 "range" | 手动验证 |
| VA-3.6.3 | ADX 边界值（25 附近）行为合理 | pytest `test_regime_adx_boundary` |
| VA-3.6.4 | 返回值类型为 Literal["trend", "range", "breakout"] | mypy 检查通过 |

### Stage 3 Review Checklist（策略多元化）

**PR 标题格式**：`[Stage-3] 策略多元化`

**前置依赖**：Stage 5 Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/strategies/active/ \
    trading/strategies/market_regime.py \
    trading/strategies/registry.py \
    trading/strategies/portfolio_manager.py

# 2. 代码风格
.venv/bin/ruff check trading/strategies/active/ \
    trading/strategies/market_regime.py \
    trading/strategies/registry.py \
    trading/strategies/portfolio_manager.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_mean_reversion.py \
    tests/unit/test_breakout.py \
    tests/unit/test_market_regime.py \
    tests/unit/test_strategy_registry.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_multi_strategy_integration.py -v

# 5. 覆盖率（策略 ≥ 85%）
.venv/bin/pytest --cov=trading/strategies \
    --cov-fail-under=85 --cov-report=term-missing
```

**功能验证检查**：
- [ ] T3.1: pytest `test_strategy_registry_register` 通过
- [ ] T3.1: pytest `test_strategy_registry_get` 通过
- [ ] T3.2: pytest `test_mean_reversion_backtest` 通过
- [ ] T3.2: pytest `test_mean_reversion_registry` 通过
- [ ] T3.3: pytest `test_breakout_backtest` 通过
- [ ] T3.4: pytest `test_ai_only_strategy_generates_signal` 通过
- [ ] T3.5: pytest `test_portfolio_manager_allocate_equity` 通过
- [ ] T3.5: pytest `test_portfolio_manager_combined_risk` 通过
- [ ] VA-3.6.1: 2023-01 BTC 趋势行情识别为 "trend"（手动验证）
- [ ] VA-3.6.2: 2023-05 BTC 震荡行情识别为 "range"（手动验证）
- [ ] VA-3.6.3: pytest `test_regime_adx_boundary` 通过
- [ ] T3.7: pytest `test_strategy_selector_trend` 通过
- [ ] T3.7: pytest `test_strategy_selector_range` 通过
- [ ] T3.8: pytest `test_strategy_params_version_history` 通过
- [ ] T3.9: Dashboard 策略切换 UI 可用（手动测试）

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `MarketRegimeDetector.detect_regime()` 中 ADX > 25 判断为 "trend"，<= 25 判断为其他（非简单二值）
- [ ] `MarketRegimeDetector` 的布林带宽度阈值（2%）有数据支撑或引用来源
- [ ] `StrategyRegistry` 在 `get_strategy()` 时策略不存在时抛出 `KeyError`（非静默返回 None）
- [ ] `PortfolioStrategyManager.validate_combined_risk()` 对所有策略汇总后的风控检查正确
- [ ] `MeanReversionStrategy` 在 `candles_15m` 数据不足时返回空信号列表（不抛异常）
- [ ] `BreakoutStrategy` 的成交量放大系数（1.5x）可配置（不在代码中 hardcoded）

边界情况：
- [ ] 无任何策略注册时 `list_strategies()` 返回空列表（不抛异常）
- [ ] `MarketRegimeDetector` 输入数据不足（< 20 条）时返回 "range"（保守判断）
- [ ] 策略产生空信号列表时 `PortfolioStrategyManager` 不抛异常
- [ ] `BreakoutStrategy` 的 Donchian Channel period 可配置

测试充分性：
- [ ] 每个策略有端到端回测测试
- [ ] `MarketRegimeDetector` 有已知数据的单元测试
- [ ] `PortfolioStrategyManager` 有多策略并发场景的集成测试

文档更新：
- [ ] `trading/strategies/active/mean_reversion.py` 有模块 docstring
- [ ] `trading/strategies/active/breakout.py` 有模块 docstring
- [ ] `config/strategies.yaml` 有每个策略的配置说明

风险评估：
- [ ] 新策略不会绕过风控（必须经过 PreFlightCheck）
- [ ] 策略选择器在 regime 判断错误时有降级策略（默认 momentum）
- [ ] `config/strategies.yaml` 中的 `enabled: false` 策略不会被意外激活

---

## 九、阶段 6：通知系统 100%

### T6.2: ApprovalFlow 审批流

**改动文件**：
- `trading/notifications/approval.py`（新建）

**实现**：
```python
class ApprovalFlow:
    PENDING_APPROVAL_TYPES = {
        "live_mode_activation",
        "large_position_open",  # > 20% 仓位
        "emergency_close_all",
    }
    DEFAULT_TIMEOUT_SECONDS = 300  # 5 分钟

    async def request_approval(
        self,
        action_type: str,
        details: dict,
        chat_id: str,
    ) -> str:
        approval_id = f"apr_{int(time.time())}_{action_type}"
        message = self._format_approval_message(action_type, details)
        await self.telegram.send(
            chat_id=chat_id,
            text=message,
            reply_markup=self._approval_keyboard(approval_id)
        )
        await self.db.save_pending_approval(approval_id, action_type, details)
        return approval_id

    async def wait_for_approval(
        self, approval_id: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    ) -> bool:
        start = time.time()
        while time.time() - start < timeout_seconds:
            status = await self.db.get_approval_status(approval_id)
            if status == "approved":
                return True
            elif status == "rejected":
                return False
            await asyncio.sleep(5)
        # 超时
        await self.db.set_approval_status(approval_id, "timeout")
        return False
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-6.2.1 | 发送审批消息到 Telegram（mock 验证）| pytest `test_approval_telegram_send` |
| VA-6.2.2 | 300s 内 approved 返回 True | pytest `test_approval_approved` |
| VA-6.2.3 | 300s 内 rejected 返回 False | pytest `test_approval_rejected` |
| VA-6.2.4 | 超时后返回 False 且状态为 timeout | pytest `test_approval_timeout` |
| VA-6.2.5 | 300s 超时后不再轮询 | mock time 验证无额外调用 |
| VA-6.2.6 | 审批写入数据库 | pytest `test_approval_db_write` |
| VA-6.2.7 | 覆盖率 ≥ 90% | `pytest --cov=trading/notifications/approval --cov-fail-under=90` |

### Stage 6 Review Checklist（通知系统 100%）

**PR 标题格式**：`[Stage-6] 通知系统 100%`

**前置依赖**：Stage 4a（WebSocket）Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/notifications/approval.py \
    trading/notifications/base.py trading/dashboard_api/websocket_manager.py

# 2. 代码风格
.venv/bin/ruff check trading/notifications/approval.py \
    trading/notifications/base.py trading/dashboard_api/websocket_manager.py

# 3. 单元测试
.venv/bin/pytest tests/unit/test_approval_flow.py \
    tests/unit/test_notification_levels.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_notification_integration.py -v

# 5. 覆盖率（通知 ≥ 80%）
.venv/bin/pytest --cov=trading/notifications \
    --cov-fail-under=80 --cov-report=term-missing
```

**功能验证检查**：
- [ ] T6.1: AlertLevel 枚举正确（INFO/WARNING/ERROR/CRITICAL）
- [ ] T6.1: pytest `test_alert_level_classification` 通过
- [ ] VA-6.2.1: pytest `test_approval_telegram_send` 通过
- [ ] VA-6.2.2: pytest `test_approval_approved` 通过
- [ ] VA-6.2.3: pytest `test_approval_rejected` 通过
- [ ] VA-6.2.4: pytest `test_approval_timeout` 通过
- [ ] VA-6.2.5: pytest `test_approval_no_extra_polling` 通过
- [ ] VA-6.2.6: pytest `test_approval_db_write` 通过
- [ ] T6.3: pytest `test_websocket_notification_broadcast` 通过
- [ ] T6.4: Dashboard 通知历史页面可访问（手动测试）
- [ ] T6.5: Telegram 消息格式使用 MarkdownV2（手动检查消息样式）

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `ApprovalFlow.wait_for_approval()` 超时时间 300s 可配置
- [ ] 审批流中的 Telegram 消息使用 inline keyboard button（不是 URL 链接）
- [ ] `AlertLevel.CRITICAL` 的定义符合预期：权益跌破 80% / 连续下单失败 3 次 / API 密钥验证失败
- [ ] WebSocket 通知在 Telegram 不可用时仍可推送（独立通道）
- [ ] `NotificationService.notify()` 同时发送 WebSocket 和 Telegram（不串行）

边界情况：
- [ ] Telegram Bot Token 无效时不抛异常（只 log error）
- [ ] 审批流在 300s 超时后不再 poll DB（资源清理）
- [ ] WebSocket 客户端断开后不再向该客户端推送
- [ ] 通知去重：5 分钟内相同内容不重复发送

测试充分性：
- [ ] `ApprovalFlow` 有超时 mock 时间测试（不真实等待 300s）
- [ ] `NotificationService` 有 Telegram 失败时的降级测试
- [ ] WebSocket 有断线重连的测试

文档更新：
- [ ] `trading/notifications/approval.py` 有 `ApprovalFlow` 的模块 docstring
- [ ] `config/alerts.yaml`（如新建）有告警级别定义和示例
- [ ] Dashboard 通知页面有使用说明

风险评估：
- [ ] 审批流不发送真实订单指令（只发消息）
- [ ] Telegram chat_id 不 hardcoded（来自配置文件）
- [ ] 通知消息中无敏感信息（API key / 交易策略细节）

---

## 十、阶段 7：24/7 运维体系 100%

### T7.2: Restart Loop 检测

**改动文件**：
- `trading/runtime/healer.py`

**实现**：
```python
import time
from pathlib import Path

class RestartLoopDetector:
    WINDOW_SECONDS = 300  # 5 分钟
    MAX_RESTARTS = 2

    def __init__(self, state_file: Path = Path("data/restart_count.json")):
        self.state_file = state_file

    def record_restart(self):
        state = self._read_state()
        now = time.time()
        # 清除 5 分钟外的记录
        state["restarts"] = [t for t in state["restarts"] if now - t < self.WINDOW_SECONDS]
        state["restarts"].append(now)
        self._write_state(state)

    def is_in_loop(self) -> bool:
        state = self._read_state()
        now = time.time()
        recent = [t for t in state["restarts"] if now - t < self.WINDOW_SECONDS]
        return len(recent) > self.MAX_RESTARTS

    def should_stop(self) -> bool:
        """5 分钟内超过 2 次重启 → 停止重启，保持告警"""
        return self.is_in_loop()
```

**验收标准**：

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| VA-7.2.1 | 5 分钟内第 2 次重启，`is_in_loop()` 返回 False | pytest `test_restart_loop_normal` |
| VA-7.2.2 | 5 分钟内第 3 次重启，`is_in_loop()` 返回 True | pytest `test_restart_loop_detected` |
| VA-7.2.3 | 5 分钟后重启，`is_in_loop()` 返回 False（窗口过期）| pytest `test_restart_loop_window_expired` |
| VA-7.2.4 | `should_stop()` 在 loop 时返回 True | pytest `test_restart_should_stop` |
| VA-7.2.5 | AutoHealer 在 `should_stop()` 时停止重启并告警 | pytest `test_healer_stops_on_loop` |
| VA-7.2.6 | 覆盖率 ≥ 90% | `pytest --cov=trading/runtime/healer --cov-fail-under=90` |

### Stage 7 Review Checklist（24/7 运维体系 100%）

**PR 标题格式**：`[Stage-7] 24/7 运维体系 100%`

**前置依赖**：Stage 5 Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 类型检查
.venv/bin/mypy --strict trading/runtime/healer.py \
    trading/runtime/self_check.py trading/logging/structured.py

# 2. 代码风格
.venv/bin/ruff check trading/runtime/healer.py \
    trading/runtime/self_check.py trading/logging/structured.py \
    scripts/macos_launchd_runtime.sh

# 3. 单元测试
.venv/bin/pytest tests/unit/test_healer.py \
    tests/unit/test_self_check.py \
    tests/unit/test_structured_logging.py -v

# 4. 集成测试
.venv/bin/pytest tests/integration/test_healer_integration.py -v

# 5. 覆盖率（healer ≥ 90%）
.venv/bin/pytest --cov=trading/runtime/healer \
    --cov=trading/runtime/self_check \
    --cov-fail-under=90 --cov-report=term-missing
```

**功能验证检查**：
- [ ] VA-7.2.1: pytest `test_restart_loop_normal` 通过
- [ ] VA-7.2.2: pytest `test_restart_loop_detected` 通过
- [ ] VA-7.2.3: pytest `test_restart_loop_window_expired` 通过
- [ ] VA-7.2.4: pytest `test_restart_should_stop` 通过
- [ ] VA-7.2.5: pytest `test_healer_stops_on_loop` 通过
- [ ] T7.1: pytest `test_healer_graceful_restart` 通过
- [ ] T7.3: pytest `test_self_check_all_checks` 通过
- [ ] T7.3: RuntimeSelfCheck Dashboard 端点可访问
- [ ] T7.4: `logs/struct.log` 存在且格式为 JSON（`cat logs/struct.log | jq .` 成功）
- [ ] T7.5: LaunchAgent 配置中 restart loop 检测已启用

**Human Reviewer 检查项**：

逻辑正确性：
- [ ] `RestartLoopDetector` 使用文件或 Redis 持久化重启次数（进程重启后计数不清零）
- [ ] `RestartLoopDetector` 的窗口时间为 300s（5 分钟），超过后旧记录被清除
- [ ] `AutoHealer._graceful_restart()` 在 `should_stop()` 时不执行重启（只告警）
- [ ] `RuntimeSelfCheck` 所有检查项并发执行（`asyncio.gather`），不串行阻塞
- [ ] `structlog` 配置了 JSON 输出（`format="json"`），每条日志包含 `timestamp`/`level`/`event`/`trace_id`
- [ ] LaunchAgent 的 `KeepAlive` 配置正确

边界情况：
- [ ] `RestartLoopDetector` 在 `data/restart_count.json` 不存在时自动创建
- [ ] `RestartLoopDetector` 在 `data/` 目录只读时降级（不抛异常，只 log warning）
- [ ] `RuntimeSelfCheck` 某项检查超时时返回该检查为 `timeout`（不阻塞其他检查）
- [ ] `structlog` 在日志文件无法写入时不在 stdout 输出（防止信息泄露）

测试充分性：
- [ ] `RestartLoopDetector` 有并发写入测试（两个进程同时写入）
- [ ] `AutoHealer` 有故障场景模拟测试
- [ ] `RuntimeSelfCheck` 有部分检查失败时的降级测试

文档更新：
- [ ] `trading/runtime/healer.py` 有 `AutoHealer` 的模块 docstring
- [ ] `trading/runtime/self_check.py` 有 `DiagnosticReport` 的 docstring
- [ ] `docs/runbook-operations.md` 有运维检查项说明
- [ ] `scripts/macos_launchd_runtime.sh` 有使用说明注释

风险评估：
- [ ] `_graceful_restart()` 中持仓状态持久化到 DB 不是可选的（必须成功才能重启）
- [ ] `should_stop()` 返回 True 后进程不自动退出（保持运行状态，等待人工处理）
- [ ] LaunchAgent 配置中无明文 API 密钥
- [ ] 日志文件中无明文敏感信息

---

## 十一、阶段 8：测试 100% + 文档 100%

### T8.3: 覆盖率提升

**目标覆盖率门槛**（修正版）：

| 模块 | 最低覆盖率 |
|------|---------|
| trading/execution/* | ≥ 95% |
| trading/risk/*（不含 state） | ≥ 95% |
| trading/risk/state.py | ≥ 90% |
| trading/runtime/paper_cycle.py | ≥ 95% |
| trading/strategies/exits.py | ≥ 95% |
| trading/strategies/active/*.py | ≥ 85% |
| trading/backtest/*.py | ≥ 85% |
| trading/notifications/*.py | ≥ 80% |
| trading/ai/*.py | ≥ 85% |
| **项目整体** | **≥ 85%** |

**验证命令**：
```bash
# 项目整体（失败低于 85% 则失败）
.venv/bin/pytest --cov=trading --cov-report=term-missing \
    --cov-fail-under=85 -q

# 分模块详细报告
.venv/bin/pytest --cov=trading/execution \
                 --cov=trading/risk \
                 --cov=trading/runtime/paper_cycle \
                 --cov=trading/strategies/exits \
                 --cov-report=term-missing \
                 --cov-fail-under=95
```

### Stage 8 Review Checklist（测试 100% + 文档 100%）

**PR 标题格式**：`[Stage-8] 测试 + 文档 100%`

**前置依赖**：Stage 1 ~ Stage 7 全部完成

**自动化检查**：
```bash
# 1. 项目整体覆盖率（≥ 85%）
.venv/bin/pytest --cov=trading --cov-report=term-missing \
    --cov-fail-under=85 -q

# 2. 核心模块覆盖率（≥ 95%）
.venv/bin/pytest --cov=trading/execution \
    --cov=trading/risk \
    --cov=trading/runtime/paper_cycle \
    --cov=trading/strategies/exits \
    --cov-report=term-missing \
    --cov-fail-under=95

# 3. pytest 超时诊断
.venv/bin/pytest tests/ --durations=10 -v

# 4. OpenAPI /docs 可用
curl -s http://127.0.0.1:8000/docs | grep -q "Swagger"

# 5. mypy --strict 全项目
.venv/bin/mypy --strict trading/ | head -50

# 6. ruff 全项目
.venv/bin/ruff check . | head -50
```

**功能验证检查**：
- [ ] T8.1: pytest 超时根因诊断报告存在（`docs/reports/pytest-perf-diagnostics.md`）
- [ ] T8.2: pytest `-m fast` 可正常运行（测试分桶有效）
- [ ] T8.3: 项目整体覆盖率 ≥ 85%
- [ ] T8.3: 核心模块覆盖率 ≥ 95%
- [ ] T8.4: 10 个新增测试全部通过
- [ ] T8.5: `http://127.0.0.1:8000/docs` 返回 Swagger UI
- [ ] T8.6: `docs/user-manual.md` 存在且 > 500 行
- [ ] T8.7: `docs/runbook-deployment.md` 存在且 > 200 行
- [ ] T8.8: `docs/runbook-emergency.md` 存在且 > 200 行

**Human Reviewer 检查项**：

测试质量：
- [ ] `pytest --durations=10` 最慢的测试 < 10s（如果 > 10s，必须标记 `@pytest.mark.slow`）
- [ ] 所有 `async` 函数有对应的异步测试
- [ ] 每个 `Exception` 类型有被测试
- [ ] 测试 fixture 无共享状态（`function` scope，非 `session` scope）
- [ ] mock 对象在测试结束后被正确清理
- [ ] 无 `pytest.mark.xfail` 未注明原因

测试覆盖率：
- [ ] `trading/execution/` 覆盖率 ≥ 95%
- [ ] `trading/risk/` 覆盖率 ≥ 95%
- [ ] `trading/runtime/paper_cycle.py` 覆盖率 ≥ 95%
- [ ] `trading/strategies/exits.py` 覆盖率 ≥ 95%
- [ ] 新增代码的覆盖率 ≥ 90%

文档完整性：
- [ ] `docs/user-manual.md` 包含：安装说明 / Dashboard 使用 / 策略配置 / Telegram 配置 / FAQ
- [ ] `docs/runbook-deployment.md` 包含：本地部署步骤 / 云服务器部署 / 故障排查
- [ ] `docs/runbook-emergency.md` 包含：崩溃恢复 / 人工接管 / 紧急平仓
- [ ] `/docs` Swagger UI 可展开每个 endpoint 查看请求/响应示例

代码质量：
- [ ] 无 `type: ignore` 注释（除非有明确的 trade-off 记录）
- [ ] 无 `# TODO` 注释（除非有对应的 issue 链接）
- [ ] 所有 public API 有 docstring
- [ ] 敏感操作（live trading、参数变更）有审计日志

风险评估：
- [ ] `docs/runbook-emergency.md` 中的紧急操作步骤可实际执行
- [ ] 用户手册中的配置示例与代码中的默认值一致
- [ ] OpenAPI spec 中无暴露的敏感 endpoint（如 `/admin` 需认证）

---

## 十二、阶段 9：实盘解锁评审

### T9.2: 压力测试场景

| # | 场景 | 模拟方式 | 预期结果 |
|---|------|---------|---------|
| ST-1 | 2021-05 崩盘（BTC -30%） | 历史数据回放 | 所有持仓被止损，无新信号 |
| ST-2 | 2022-11 FTX 流动性枯竭 | 模拟 API 延迟 + 成交滑点扩大 | 下单失败被正确处理，无超仓 |
| ST-3 | 网络断开 10 分钟 | mock network error | AutoHealer 触发，API 故障降级 |
| ST-4 | K 线数据中断 | mock empty candles | 冻结 symbol，告警触发 |
| ST-5 | 连续 3 次下单失败 | mock 429 错误 | symbol 冻结 60 分钟，无冒进 |

### Stage 9 Review Checklist（实盘解锁评审）

**PR 标题格式**：`[Stage-9] 实盘解锁评审`

**前置依赖**：Stage 8 Review Checklist 全部通过

**自动化检查**：
```bash
# 1. 12 项前置条件验证报告存在
test -f docs/live-trading-readiness-report.md

# 2. 压力测试全部通过
pytest tests/integration/test_stress_*.py -v

# 3. 风控链路完整（无 bypass）
grep -r "SKIP_PREFLIGHT\|SKIP_RISK\|bypass" trading/

# 4. 实盘锁定确认
grep "live_trading_lock.*False" trading/runtime/state.py
```

**功能验证检查**：
- [ ] T9.1: 12 项前置条件验证报告完整（`docs/live-trading-readiness-report.md`）
- [ ] T9.1: 回测报告存在（3 个月历史，夏普比率 > 1.0）
- [ ] T9.1: 30 天 paper 记录摘要存在
- [ ] T9.1: 测试覆盖率报告存在
- [ ] T9.1: AI 评分验证报告存在
- [ ] T9.2: ST-1 压力测试通过（崩盘场景）
- [ ] T9.2: ST-2 压力测试通过（FTX 场景）
- [ ] T9.2: ST-3 压力测试通过（网络断开）
- [ ] T9.2: ST-4 压力测试通过（数据中断）
- [ ] T9.2: ST-5 压力测试通过（连续下单失败）
- [ ] T9.3: 代码安全审计报告通过（无高危问题）
- [ ] T9.4: 实盘解锁文档存在（`docs/live-trading-unlock.md`）
- [ ] T9.5: `live_trading_lock` 默认值为 `True`（需要明确用户确认才可改为 False）

**Human Reviewer 检查项**：

实盘解锁条件验证：
- [ ] 回测夏普比率 > 1.0（有具体数值记录）
- [ ] Paper Trading 连续 30 天无崩溃日志
- [ ] 风控链路中无任何 `bypass` 关键字（`grep -r "bypass\|SKIP" trading/risk/` 无输出）
- [ ] ExitEngine 单元测试覆盖率 ≥ 95%
- [ ] AI 评分阈值经回测验证（有 ValidationResult 输出）
- [ ] Telegram 告警已实际发送测试（截图或日志证明）
- [ ] AutoHealer 已通过 Chaos Monkey 测试（手动模拟故障）
- [ ] API 密钥不在代码中明文（所有 key 来自环境变量或 Keychain）
- [ ] 1 USDT 测试单已执行（有 Binance 成交记录截图）
- [ ] 代码 review 至少 1 人 approved
- [ ] 损失上限配置存在（单日最大亏损 < 5%）

压力测试验证：
- [ ] ST-1: 模拟 2021-05 崩盘时，所有 LONG 持仓被止损，无新信号发出
- [ ] ST-2: 模拟 FTX 事件时，滑点扩大但无超仓，订单失败被正确处理
- [ ] ST-3: 网络断开 10 分钟后，AutoHealer 触发，API 故障降级正确
- [ ] ST-4: K 线数据中断时，symbol 被冻结，告警触发
- [ ] ST-5: 连续 3 次下单失败后，symbol 冻结 60 分钟，无冒进下单

风险评估：
- [ ] 用户已签署风险披露（`docs/risk-disclosure.md` 存在且已签字）
- [ ] 损失上限在代码中被强制执行（非仅文档说明）
- [ ] `live_trading_lock` 的解锁需要双重确认（UI 确认 + 配置文件修改）

---

### Stage 10 Review Checklist（实盘灰度 100%）

**PR 标题格式**：`[Stage-10] 实盘灰度 100%`

**前置依赖**：Stage 9 Review Checklist 全部通过 + `live_trading_lock = False`

**自动化检查**：
```bash
# 1. 实盘锁定已解除
grep "live_trading_lock.*False" trading/runtime/state.py

# 2. 实盘数据写入 live_trades 表（而非 paper_trades）
sqlite3 data/crypto_trader.db \
  "SELECT COUNT(*) FROM live_trades WHERE timestamp > datetime('now', '-1 day');"

# 3. 告警通道畅通
curl -s -X POST https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage \
  -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=实盘监控测试" | grep '"ok":true'
```

**功能验证检查**：
- [ ] T10.1: 小资金账户配置存在（`config/live-minimal.yaml`，max_position = 50 USDT）
- [ ] T10.1: 实盘监控 Dashboard 可访问
- [ ] T10.2: 首日实盘运行正常（无崩溃、无超仓）
- [ ] T10.2: 实盘日志中无 ERROR（排除正常的市场关闭）
- [ ] T10.3: 3 次小资金实测执行成功（每笔 10-50 USDT，有成交记录）
- [ ] T10.3: Telegram 告警通道畅通
- [ ] T10.3: 自动平仓功能测试（手动触发或等自然触发）
- [ ] T10.4: 人工接管流程文档存在
- [ ] T10.4: 人工接管期间 `live_trading_lock` 设为 `True`（防止自动交易）
- [ ] T10.5: 单日亏损阈值测试（模拟亏损达到阈值时自动停止）
- [ ] T10.5: 实盘止损触发后，有 Telegram 告警通知
- [ ] T10.6: 新策略 A/B 测试框架存在（有分桶配置）
- [ ] T10.7: 实盘运行 7 天无崩溃（日志无 ERROR）

**Human Reviewer 检查项**：

实盘安全验证：
- [ ] `live_trading_lock` 在实盘启动前为 `False`（已解锁）
- [ ] `config/live-minimal.yaml` 中 `max_position ≤ 50 USDT`
- [ ] 所有 Binance API Key 来自环境变量，无明文 key 在代码中
- [ ] 实盘启动前 `live_trades` 表存在且 schema 正确
- [ ] `max_daily_loss_pct` 和 `max_position_pct` 在配置中有值

实盘操作验证：
- [ ] Telegram 告警在每次开仓/平仓/止损时发送（查看实际消息截图）
- [ ] Dashboard 的 P&L 计算正确（与 Binance 实际持仓对比）
- [ ] 模拟亏损达到阈值时，系统停止开新仓位（有日志记录）
- [ ] 人工接管期间 `live_trading_lock = True`（防止自动恢复）
- [ ] 策略 A/B 分桶配置正确（`strategy_name` 字段有区分）

风险评估：
- [ ] `live_trading_lock` 解锁需要人工确认（不只是代码默认值）
- [ ] 实盘账户资金 < 100 USDT（确保是小资金灰度）
- [ ] 止损触发后不自动重新开启（需要人工确认）
- [ ] 实盘日志中无敏感信息泄露（API secret 已脱敏）
- [ ] 新策略上线前有回测验证报告（夏普比率 > 0.5）

---

## 十三、关键路径依赖图（完整版）

```
关键路径（串行）:
阶段0 → 阶段1 → 阶段2/2b → 阶段5.1-5.2 → 阶段3 → 阶段9 → 阶段10
                                  ↓
可并行（不受关键路径约束）:
阶段4（Dashboard WebSocket → Dashboard UI）
阶段6（通知系统）← 需要阶段4的WebSocket
阶段7（24/7运维）← 需要阶段5
阶段8（测试+文档）← 需要所有阶段完成
```

---

## 十四、完整验收清单（检查表）

### 阶段 0（1-3 天）- 安全修复
- [ ] VA-0.1.1 ~ VA-0.1.5: slippage 配置
- [ ] VA-0.2.1 ~ VA-0.2.6: runner 异常处理
- [ ] VA-0.3.1 ~ VA-0.3.5: consecutive_losses 隔离
- [ ] VA-0.4.1 ~ VA-0.4.5: slippage 回溯修正
- [ ] CR 审查通过（mypy/ruff/pytest 全部 green）

### 阶段 1（1-2 周）- 退出策略
- [ ] VA-1.1.1 ~ VA-1.1.3: ExitConfig
- [ ] VA-1.2.1 ~ VA-1.2.6: ExitEngine 逻辑
- [ ] VA-1.3.1 ~ VA-1.3.5: ExitEngine 串联
- [ ] VA-1.4.1 ~ VA-1.4.3: ExitConfig YAML
- [ ] CR 审查通过

### 阶段 2（3-4 周）- 回测框架 + 因子库
- [ ] VA-2.1.1 ~ VA-2.1.4: Parquet 存储
- [ ] VA-2.2.1 ~ VA-2.2.4: BinanceHistoricalLoader
- [ ] VA-2.3.1 ~ VA-2.3.6: BacktestEngine
- [ ] VA-F1.1 ~ VA-F11.6: 11 个因子函数
- [ ] CR 审查通过

### 阶段 2b（1 周）- 数据迁移
- [ ] VA-2b.1 ~ VA-2b.7: 数据库迁移
- [ ] CR 审查通过

### 阶段 5.1-5.2（2 周）- 风控链路
- [ ] VA-5.1.1 ~ VA-5.1.8: PreFlightCheck
- [ ] VA-5.2.1 ~ VA-5.2.5: PositionMonitor
- [ ] VA-5.5.1 ~ VA-5.5.5: ScoreValidator
- [ ] CR 审查通过

### 阶段 3（2-3 周）- 策略多元化
- [ ] T3.1 ~ T3.9: 全部策略任务
- [ ] CR 审查通过

### 阶段 4（3-4 周）- Dashboard
- [ ] T4.1 ~ T4.9: 全部 Dashboard 任务
- [ ] CR 审查通过

### 阶段 6（1 周）- 通知系统
- [ ] T6.1 ~ T6.5: 全部通知任务
- [ ] CR 审查通过

### 阶段 7（2 周）- 24/7 运维
- [ ] VA-7.2.1 ~ VA-7.2.6: Restart Loop 检测
- [ ] T7.1, T7.3 ~ T7.5: AutoHealer/SelfCheck/日志
- [ ] CR 审查通过

### 阶段 8（2-3 周）- 测试 + 文档
- [ ] 项目整体覆盖率 ≥ 85%
- [ ] 核心模块覆盖率 ≥ 95%
- [ ] OpenAPI /docs 可用
- [ ] 用户手册完整

### 阶段 9（1-2 周）- 实盘评审
- [ ] ST-1 ~ ST-5 压力测试全部通过
- [ ] 12 项前置条件全部满足

### 阶段 10（2-4 周）- 实盘灰度
- [ ] Phase A/B/C 灰度验证成功
- [ ] 实盘对账无误

---

*v1: 2026-04-21-100percent-completion-plan.md*
*v2: 2026-04-21-v2-optimized-plan.md*
*v3 Final: 2026-04-21-v3-final-plan.md*
