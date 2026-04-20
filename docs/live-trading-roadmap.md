# 加密货币 AI 交易系统落地路线图

> 本文档由 Claude Code 专家辩论生成，综合了量化策略专家、技术架构专家、风控专家三方观点。
> 文档供 Codex 等 AI Agent 后续多轮迭代优化使用。

---

## 一、现状评估

### 当前系统能力 vs 落地缺口

| 模块 | 现状 | 缺口 |
|------|------|------|
| 蜡烛图数据获取 | ✅ 正常 | — |
| 多时间帧特征工程 | ✅ 正常 | — |
| AI 评分抽象层 | ✅ 已实现 | 评分标准未经回测验证 |
| 风险配置文件 | ✅ 存在 | 未强制执行 |
| 纸交易执行 | ✅ 已实现 | 无出场逻辑 |
| SQLite 事件日志 | ✅ 完整 | 无 PnL 归因分析 |
| Telegram 告警 | ✅ 已实现 | — |
| Supervisor 进程管理 | ✅ 正常 | — |
| Dashboard 状态展示 | ✅ 已实现 | 无实时持仓同步 |
| **出场逻辑** | ❌ 完全缺失 | 只有 BUY，无止损/止盈/时间退出 |
| **回测框架** | ❌ 完全缺失 | 无法验证策略有效性 |
| **实盘下单** | ❌ 只有 K 线读取 | 无真实交易所下单能力 |
| **风控强制执行** | ⚠️ 配置存在 | 部分链路未强制执行 |

### 核心安全缺陷

1. **零滑点**：`PaperExecutor` slippage_bps=0，纸交易表现被严重高估
2. **API 故障只记录不停止**：`runner.py` 异常处理是"记录+继续"，这是量化灾难常见起源
3. **consecutive_losses 跨 symbol 泄漏**：一个 symbol 的连续亏损会影响所有 symbol 的风控判断
4. **仓位重建数据一致性**：DB 读取和实盘成交之间存在竞态条件

---

## 二、专家辩论裁定

### 辩题：出场逻辑 vs 回测框架 — 谁先谁后？

| 专家 | 立场 |
|------|------|
| 量化策略专家 | 出场逻辑必须优先。没有出场规则的策略不是策略，是赌博。 |
| 技术架构专家 | 回测框架优先。没有回测验证的出场参数，是用真钱为无知付学费。 |

**裁定**：两者必须**并行**推进，不是先后问题。

- 策略专家对的是：没有出场逻辑不能叫策略（正确）
- 架构专家对的是：出场参数不能拍脑袋决定（正确）
- **真正的问题不是"谁先谁后"，而是"怎么同时做"**

### 风控专家揭示的关键盲点

两位辩论专家都没提到的问题：

> **纸交易的滑点 = 0，但实盘滑点可能是 50-500 bps。**
> 回测和实盘之间存在巨大的执行差距鸿沟。

---

## 三、落地方案：六阶段并行推进

### 阶段 0：立即修复（不延迟，1-2 天）

#### 0.1 修复零滑点 — 高优先级

**问题**：`PaperExecutor` 默认 slippage_bps=0，纸交易结果完全不可信。

**修复方案**：按币种分级配置滑点估算。

```python
# trading/execution/paper_executor.py
class PaperExecutor:
    SLIPPAGE_BY_TIER = {
        "BTCUSDT": Decimal("5"),   # bps
        "ETHUSDT": Decimal("8"),
        "BNB": Decimal("10"),
        "SOL_AVAX": Decimal("25"),
        "ALT": Decimal("50"),
        "MEME_NEW": Decimal("100"),
    }

    def __init__(
        self,
        fee_bps: Decimal = Decimal("10"),
        slippage_bps: Decimal = None,  # 改为可选
        symbol: str = None,            # 新增
    ):
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps or self.SLIPPAGE_BY_TIER.get(
            symbol, Decimal("20")
        )
```

**同时更新 `config/strategies.yaml`**：

```yaml
execution:
  default_fee_bps: 10
  default_slippage_bps: 20
  slippage_tiers:
    BTCUSDT: 5
    ETHUSDT: 8
    SOLUSDT: 25
    DEFAULT: 50
```

#### 0.2 API 故障降级链路 — 高优先级

**问题**：`runner.py` 的异常处理只记录事件并继续，这是量化灾难的常见起源。

**修复方案**：分级响应，不同故障类型不同处理。

```python
# trading/runtime/runner.py
class APIFailureDegradation:

    @staticmethod
    def handle_market_data_failure(symbol: str, session_factory) -> bool:
        """行情数据获取失败 → 跳过该 symbol，发出告警"""
        events_repo.record_event(
            event_type="market_data_failed",
            severity="warning",
            component="runner",
            message=f"Market data unavailable for {symbol}, skipping cycle",
        )
        return False  # 不继续处理该 symbol

    @staticmethod
    def handle_order_failure(symbol: str, error: Exception, session_factory) -> None:
        """订单下单失败 → 立即告警，不自动暂停（避免网络抖动导致全局停止）"""
        events_repo.record_event(
            event_type="order_failed_critical",
            severity="critical",
            component="runner",
            message=f"Order failed for {symbol}: {error}",
        )
        raise  # 让上层决定是否继续

    @staticmethod
    def handle_balance_failure(session_factory) -> None:
        """余额查询失败 → 暂停所有交易，直到人工确认"""
        events_repo.record_event(
            event_type="balance_check_failed_critical",
            severity="critical",
            component="runner",
            message="Account balance check failed, pausing all trading",
        )
        raise RuntimeError("Balance check failed, trading paused")
```

---

### 阶段 1：出场逻辑实现（2-3 周）

#### 1.1 出场信号优先级体系

```
P0 硬止损：任何情况下都不能绕过
P1 止盈：达到目标价立即执行
P2 趋势退出：15m 趋势从 up 变 down
P3 时间退出：持仓超 N 根 K 线
P4 仓位再平衡：总仓位超 80% 强制止盈一半
```

#### 1.2 新建 `trading/strategies/exits.py`

```python
from decimal import Decimal
from dataclasses import dataclass
from trading.features.builder import CandleFeatures
from trading.portfolio.accounting import Position

@dataclass(frozen=True)
class ExitSignal:
    reason: str          # "hard_stop" | "take_profit" | "trend_exit" | "time_exit" | "rebalance"
    exit_price: Decimal
    pnl_pct: Decimal
    urgency: int         # 0=下次market_order, 1=立即

class ExitEngine:
    def __init__(
        self,
        stop_loss_atr: Decimal = Decimal("2.0"),
        take_profit_atr: Decimal = Decimal("3.0"),
        max_bars_held: int = 8,
        trend_exit_enabled: bool = True,
        rebalance_threshold_pct: Decimal = Decimal("80"),
    ):
        self.stop_loss_atr = stop_loss_atr
        self.take_profit_atr = take_profit_atr
        self.max_bars_held = max_bars_held
        self.trend_exit_enabled = trend_exit_enabled
        self.rebalance_threshold_pct = rebalance_threshold_pct

    def check_exit(
        self,
        position: Position,
        entry_price: Decimal,
        atr_14: Decimal,
        bars_held: int,
        features_15m: list[CandleFeatures],
        total_position_pct: Decimal,
    ) -> ExitSignal | None:
        """优先级：P0 > P1 > P2 > P3 > P4"""
        latest = features_15m[-1]

        # P0: 硬止损
        stop_price = entry_price - (atr_14 * self.stop_loss_atr)
        if latest.close < stop_price:
            return ExitSignal("hard_stop", stop_price,
                (stop_price - entry_price) / entry_price * 100, urgency=1)

        # P1: 止盈
        profit_price = entry_price + (atr_14 * self.take_profit_atr)
        if latest.close >= profit_price:
            return ExitSignal("take_profit", latest.close,
                (latest.close - entry_price) / entry_price * 100, urgency=0)

        # P2: 趋势退出
        if self.trend_exit_enabled and latest.trend_state == "down":
            return ExitSignal("trend_exit", latest.close,
                (latest.close - entry_price) / entry_price * 100, urgency=1)

        # P3: 时间退出
        if bars_held >= self.max_bars_held:
            return ExitSignal("time_exit", latest.close,
                (latest.close - entry_price) / entry_price * 100, urgency=0)

        # P4: 再平衡
        if total_position_pct >= self.rebalance_threshold_pct:
            return ExitSignal("rebalance", latest.close,
                (latest.close - entry_price) / entry_price * 100, urgency=0)

        return None
```

#### 1.3 出场逻辑集成到 `run_paper_cycle`

在 Stage 2（原来只有 candidate generation）增加持仓出场检查：

```python
# Stage 2（修改后）: 先检查持仓出场信号，再生成新入场信号
open_positions = account.positions
for symbol, position in open_positions.items():
    exit_signal = exit_engine.check_exit(
        position=position,
        entry_price=position.avg_entry_price,
        atr_14=latest_15m.atr_14,
        bars_held=position.bars_held,  # Position 中新增字段
        features_15m=features_15m,
        total_position_pct=total_position_pct,
    )
    if exit_signal:
        executor.execute_exit(position, exit_signal, market_price)
```

#### 1.4 `PortfolioAccount` 需要新增的字段

```python
class Position(BaseModel):
    symbol: str
    qty: Decimal = Field(ge=0)
    avg_entry_price: Decimal = Field(ge=0)
    fees_paid_usdt: Decimal = Field(default=Decimal("0"), ge=0)
    bars_held: int = 0              # 新增：持仓K线数
    opened_at: datetime | None = None  # 新增：开仓时间

    def apply_sell_fill(self, fill: PaperFill) -> None:
        """实现卖出逻辑，关闭或部分关闭持仓"""
        # ... 从持仓中扣减数量，更新均价
```

#### 1.5 参数配置化

**更新 `config/strategies.yaml`**：

```yaml
strategies:
  active:
    multi_timeframe_momentum:
      enabled: true
      symbols: [BTCUSDT, ETHUSDT, SOLUSDT]

      entry:
        atr_multiplier: 2.0
        rsi_14_min: 45
        ema_crossover_required: true
        min_volume_24h_usdt: 1000000
        min_atr_14: 0.0001

      exit:
        stop_loss_atr: 2.0           # P0 硬止损
        take_profit_atr: 3.0         # P1 止盈 (1.5:1 R/R)
        max_bars_held: 8             # P3 时间退出
        trend_exit_enabled: true      # P2 趋势退出
        rebalance_threshold_pct: 80   # P4 再平衡

execution:
  fee_bps: 10
  slippage_tiers:
    BTCUSDT: 5
    ETHUSDT: 8
    SOLUSDT: 25
    DEFAULT: 50
```

---

### 阶段 2：回测框架（3-4 周，与阶段 1 并行）

#### 2.1 目录结构

```
trading/backtest/
├── engine.py              # 核心引擎
├── data_provider.py       # 历史数据接口
├── order_simulator.py     # 订单模拟（支持市价/限价/止损）
├── portfolio_simulator.py # 组合模拟
├── metrics.py             # 绩效指标计算
└── optimizer.py            # 参数优化（网格搜索）
```

**核心原则**：回测引擎和实盘引擎必须使用完全相同的策略逻辑（只是数据源不同）。

#### 2.2 回测引擎核心

```python
# trading/backtest/engine.py
class BacktestEngine:
    def __init__(
        self,
        symbols: list[str],
        start_date: datetime,
        end_date: datetime,
        initial_cash: Decimal,
        fee_bps: Decimal = Decimal("10"),
        slippage_bps: Decimal = Decimal("20"),
    ):
        self.symbols = symbols
        self.initial_cash = initial_cash
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def run(
        self,
        entry_strategy,      # 与实盘共用同一个 strategy module
        exit_strategy,       # 与实盘共用同一个 exit module
        params: dict,        # 策略参数
    ) -> BacktestResult:
        """
        1. 从历史数据加载 K 线
        2. 对每个 symbol 执行 run_paper_cycle（修改数据源）
        3. 模拟订单成交（fee + slippage）
        4. 计算绩效指标
        5. 返回 equity_curve + trades + metrics
        """
```

#### 2.3 必须计算的绩效指标

| 指标 | 合格线 | 说明 |
|------|--------|------|
| Total Return | > 0 | 至少跑赢不交易 |
| Annualized Return | > 20% | 年化收益目标 |
| Max Drawdown | < 20% | 单次最大回撤 |
| Sharpe Ratio | > 1.0 | 风险调整后收益 |
| Win Rate | > 40% | 配合 1.5:1 R/R 有意义 |
| Avg Bars Held | 4-12 | 验证时间退出参数 |
| Max Single Loss | < 5% | 单次最大亏损 |
| Profit Factor | > 1.5 | 盈利总额/亏损总额 |

#### 2.4 参数优化

```python
# trading/backtest/optimizer.py
class ParameterOptimizer:
    def grid_search(
        self,
        param_grid: dict[str, list],
        metric: str = "sharpe_ratio",
    ) -> OptimizationResult:
        """
        网格搜索最优参数。
        注意：必须使用 out-of-sample testing
        - 70% 数据训练，30% 数据验证
        - 或使用 walk-forward analysis（滚动窗口）
        """
        param_grid = {
            'stop_loss_atr': [1.5, 2.0, 2.5, 3.0],
            'take_profit_atr': [2.0, 3.0, 4.0],
            'max_bars_held': [4, 8, 12, 16],
            'rsi_14_min': [35, 45, 55],
        }
```

---

### 阶段 3：交易所集成（阶段 1+2 完成后，2-3 周）

#### 3.1 Binance API 权限矩阵

| 权限 | 用途 | 风险 |
|------|------|------|
| `enableReadOnly` | 读取余额、订单 | 无风险 |
| `Enable Spot & Margin Trading` | 现货买卖 | **高风险** |
| `Enable Futures` | 绝对不要 | **极高风险** |
| `Enable Withdrawals` | 绝对不要 | **致命风险** |

**操作步骤**：
1. Binance → API Management → Create API
2. 只勾选 "Enable Spot & Margin Trading"
3. 设置 IP 白名单
4. API Key/Secret 存入 `.env`（永远不提交 git）

#### 3.2 新建 `trading/execution/live_executor.py`

```python
class LiveExecutor:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        fee_bps: Decimal = Decimal("10"),
    ):
        self.client = binance.Client(api_key, api_secret, testnet=testnet)
        self.fee_bps = fee_bps

    def place_market_buy(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
    ) -> OrderResult:
        # 1. 验证最小下单量
        min_qty = self._get_min_quantity(symbol)
        if quantity < min_qty:
            raise OrderError(f"Quantity {quantity} below minimum {min_qty}")

        # 2. 精度截断
        qty = self._floor_quantity(symbol, quantity)

        # 3. 调用 Binance API
        try:
            order = self.client.order_market_buy(symbol=symbol, quantity=float(qty))
        except BinanceAPIException as e:
            if e.code == -1013:
                raise OrderError(f"Adjusted quantity too small: {e}")
            raise

        # 4. 轮询等待成交
        return self._wait_for_fill(order['orderId'])

    def _wait_for_fill(self, order_id: int, timeout: int = 30):
        start = time.time()
        while time.time() - start < timeout:
            order = self.client.get_order(symbol=self.symbol, orderId=order_id)
            if order['status'] == 'FILLED':
                return Decimal(str(order['executedQty'])), Decimal(str(order['avgPrice']))
            time.sleep(0.5)
        raise OrderError(f"Order {order_id} fill timeout")
```

#### 3.3 WebSocket 实时成交推送（可选但强烈建议）

```python
class BinanceWebSocketListener:
    """监听 Binance User Data Stream，实时同步订单状态"""

    def start(self, api_key: str, on_order_update: callable):
        self.client.user_data(api_key=api_key, on_message=self._handle_message)

    def _handle_message(self, msg):
        event_type = msg['e']  # executionReport / balanceUpdate
        self.on_order_update(msg)
```

---

### 阶段 4：风控强制化（贯穿所有阶段）

#### 4.1 新建 `trading/risk/enforcer.py`

```python
class RiskEnforcer:
    def pre_cycle_check(
        self,
        account: PortfolioAccount,
        day_start_equity: Decimal,
        market_prices: dict[str, Decimal],
    ) -> CheckResult:
        """
        每个 cycle 开始前必须通过所有风控检查。
        任一检查失败 → cycle 跳过，不下单。
        """
        # 1. 日内亏损检查（-7% → 禁止开仓）
        daily_pnl_pct = (account.total_equity(market_prices) - day_start_equity) / day_start_equity
        if daily_pnl_pct <= Decimal("-0.07"):
            return CheckResult(approved=False, reason="daily_loss_exceeded_7pct")

        # 2. 全局仓位上限（70%）
        total_pos_pct = account.total_position_pct(market_prices)
        if total_pos_pct >= Decimal("70"):
            return CheckResult(approved=False, reason="total_position_exceeded_70pct")

        # 3. 单币种仓位上限（30%，每个持仓检查）
        for symbol, position in account.positions.items():
            pos_pct = (position.qty * market_prices[symbol]) / account.total_equity(market_prices)
            if pos_pct >= Decimal("30"):
                return CheckResult(approved=False, reason=f"symbol_{symbol}_position_exceeded_30pct")

        # 4. 开仓次数限制
        if account.daily_order_count >= MAX_DAILY_ORDERS:
            return CheckResult(approved=False, reason="daily_order_limit_reached")

        return CheckResult(approved=True)
```

#### 4.2 新建 `trading/risk/circuit_breaker.py`

```python
class CircuitBreaker:
    """独立于交易主循环的监控，每分钟检查一次"""

    def check_all(self, session_factory, market_prices: dict) -> list[Alert]:
        alerts = []
        account = self._load_account(session_factory)

        # 1. 权益创日内新低
        if account.equity < account.day_low:
            alerts.append(Alert(level="critical", message="Equity below day low"))

        # 2. 持仓超时（超24h无浮动盈亏变化）
        for symbol, pos in account.positions.items():
            if pos.age_hours > 24 and abs(pos.unrealized_pnl_pct) < Decimal("0.5"):
                alerts.append(Alert(level="warning", message=f"Position {symbol} stale"))

        # 3. 订单 PENDING 超时（>5min）
        for order in account.pending_orders:
            if order.age_minutes > 5:
                alerts.append(Alert(level="critical", message=f"Order {order.id} pending timeout"))

        return alerts
```

---

### 阶段 5：测试网验证（2-4 周）

**绝对规则**：真实资金入场前，必须在测试网通过所有验证。

#### 5.1 测试网验证清单

```
□ 完整买卖流程：充值 USDT → 买入 → 持仓 → 卖出 → 提现
□ 止损单触发：挂一个止损单，验证能在 testnet 触发
□ 余额同步：Dashboard 显示的余额与 Binance testnet 一致
□ 告警通道：Telegram 告警能正常推送
□ API 错误处理：故意制造 API 错误，验证系统行为正确
□ 24/7 稳定性：测试网连续运行 2 周无崩溃
```

#### 5.2 实盘小额定金验证（2-4 周）

```
第1周：观察策略执行是否符合预期
第2周：验证止损/止盈是否正确触发
第3周：验证 Dashboard 同步和告警
第4周：确认所有链路无误，逐步加码
```

---

### 阶段 6：生产部署与运营

#### 6.1 服务器推荐配置

```
地区：新加坡/日本（靠近 Binance 服务器）
规格：2核4G最低，推荐4核8G
硬盘：50GB SSD
网络：固定 IP，绑定 Binance API 白名单
```

#### 6.2 运营监控指标

| 指标 | 阈值 | 告警级别 |
|------|------|---------|
| 单日亏损 | > 7% | Critical |
| 单笔亏损 | > 5% | Warning |
| 持仓超24h | > 24h | Warning |
| 订单pending | > 5min | Critical |
| API错误率 | > 10% | Critical |
| 权益创日内新低 | — | Warning |

---

## 四、关键文件修改清单

| 文件 | 修改内容 | 阶段 |
|------|---------|------|
| `trading/execution/paper_executor.py` | 添加分级滑点模型 | 0 |
| `trading/runtime/runner.py` | API 故障降级链路 | 0 |
| `trading/strategies/exits.py` | **新建**：出场引擎 | 1 |
| `trading/risk/enforcer.py` | **新建**：风控强制执行 | 4 |
| `trading/risk/circuit_breaker.py` | **新建**：独立监控 | 4 |
| `trading/backtest/engine.py` | **新建**：回测引擎 | 2 |
| `trading/backtest/optimizer.py` | **新建**：参数优化器 | 2 |
| `trading/execution/live_executor.py` | **新建**：实盘执行器 | 3 |
| `config/strategies.yaml` | 出场参数配置化 | 1 |

---

## 五、Codex 审查提示词

```
请分析以下加密货币AI纸交易系统的落地路线图方案（docs/live-trading-roadmap.md）：

1. **识别遗漏风险**：方案中是否有我没有考虑到的风险点？
   - 技术风险（架构层面）
   - 交易风险（策略层面）
   - 操作风险（运营层面）
   - 市场风险（加密货币特性）

2. **评估各阶段优先级**：是否有阶段顺序需要调整？
   - 阶段0的立即修复是否完整？
   - 阶段1和阶段2并行的依赖关系是否清晰？
   - 是否有更优的并行策略？

3. **检验风控完整性**：
   - 风控强制链路是否有漏洞？
   - CircuitBreaker 是否能覆盖所有极端情况？
   - 是否有"风控旁路"被绕过的可能？

4. **验证出场逻辑**：
   - 出场信号优先级设计是否合理？
   - 多个信号同时触发时的决策是否明确？
   - 止盈止损是否考虑了滑点和流动性？

5. **回测框架审查**：
   - 回测引擎与实盘引擎的代码复用方式是否可行？
   - out-of-sample testing 的具体实现细节是否足够？
   - 绩效指标是否全面？

6. **实盘集成审查**：
   - Binance API 集成有哪些边界情况没有处理？
   - WebSocket 断连重连策略是什么？
   - 订单状态同步的竞态条件如何处理？

7. **补充建议**：
   - 哪些功能点应该优先实现？
   - 哪些风险应该提前设计防御措施？
   - 运营阶段有哪些必须有的监控指标？

请给出具体的改进建议和潜在问题点。如果发现方案有明显漏洞，请直接指出。
```

---

## 六、落地检查清单

```
上线前必须全部完成：

纸交易阶段：
□ 修复零滑点问题（立即）
□ API 故障降级链路（立即）
□ 出场逻辑实现（阶段1）
□ 回测框架搭建（阶段2）
□ 6个月历史回测通过（Sharpe>1.0, MaxDD<20%）
□ 参数优化完成

测试网阶段：
□ 完整买卖流程验证
□ 止损单触发验证
□ 告警通道验证
□ 2周稳定性测试

实盘阶段：
□ 小额定金 $50-100 运行 2周
□ Dashboard 同步验证
□ 逐步加码到正常资金量

运营阶段：
□ 每日复盘交易记录
□ 每周回测验证策略有效性
□ 每月参数评估
```

---

## 七、验证方法

| 阶段 | 验证方式 |
|------|---------|
| 阶段0 | 纸交易运行1周，观察 equity curve 合理性 |
| 阶段1 | 日志中检查 exit 信号是否正确触发 |
| 阶段2 | 回测 equity curve 与纸交易 equity curve 方向一致性 |
| 阶段3 | 测试网下单是否成功成交，Binance 余额正确扣减 |
| 阶段4 | 故意触发风控条件（如日内亏损>7%），验证阻止开仓 |
| 阶段5 | 连续2周测试网稳定运行 |
| 阶段6 | 小额定金验证3周无异常 |
