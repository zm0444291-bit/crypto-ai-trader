# Crypto AI Trader System Design

Date: 2026-04-19
Project: `crypto-ai-trader`
Status: Approved design draft

## 1. Goal

Build a local-first AI-assisted cryptocurrency quantitative trading system that can run 24/7, begin with automatic paper trading, and later support small-capital live spot trading.

The first production target is not high-frequency trading, market making, or cross-exchange arbitrage. The first target is a controlled, explainable, medium-frequency Binance spot system with strong risk controls, a local dashboard, Telegram alerts, and a path from paper trading to live small-capital automation.

Initial live capital target:

- 100-500 USDT
- Binance spot
- Main pairs: BTCUSDT, ETHUSDT, SOLUSDT
- Medium-frequency signals using 15m and 1h, with 4h trend context

## 2. Core Decisions

The first version uses a research/trading separation model with a lightweight local runtime.

Chosen approach:

- `research/` for backtests, notebooks, reports, and parameter experiments
- `trading/` for the 24/7 runtime, risk, execution, AI scoring, storage, and dashboard API
- `dashboard/` for the local web control panel

The system starts locally on the user's computer for easier debugging. After stable paper and small live runs, it can migrate to a VPS or cloud server.

Default first mode:

```text
trade_mode = paper_auto
live_trading_enabled = false
```

Target later mode:

```text
trade_mode = live_small_auto
live_trading_enabled = true
capital_cap = 100-500 USDT
```

## 3. System Architecture

```text
Binance Market Data
  -> Market Data Service
  -> Feature Builder
  -> Rule Strategy Engine
  -> Trade Candidate
  -> AI Scoring Engine
  -> Risk Engine
  -> Position Sizer
  -> Execution Gate
  -> Paper Executor by default
  -> Portfolio / Orders / Fills
  -> SQLite
  -> Dashboard + Telegram
```

Live execution is reserved behind a double lock:

```text
Execution Gate
  -> Paper Executor
  -> Live Shadow Executor
  -> Live Binance Spot Executor
```

AI is never allowed to bypass deterministic controls.

Rules:

- AI cannot create trades from nothing.
- AI can only score rule-generated trade candidates.
- RiskEngine always runs after AI scoring.
- ExecutionGate decides whether the order is paper, shadow, live, paused, or blocked.
- Kill Switch can block all new actions.

## 4. MVP Modules

### 4.1 Market Data Service

Responsibilities:

- Fetch Binance spot candles.
- Support BTCUSDT, ETHUSDT, SOLUSDT.
- Support 15m, 1h, and 4h timeframes.
- Store candles in SQLite.
- Detect missing, duplicate, delayed, or abnormal candles.

Out of scope:

- Strategy decisions
- Order execution
- Portfolio mutation

### 4.2 Feature Builder

Responsibilities:

- Convert raw candles into indicators and market states.
- Calculate EMA, RSI, ATR, volume ratio, breakout levels, trend state, and volatility state.
- Provide features to strategy and dashboard.

### 4.3 Rule Strategy Engine

Active strategy:

```text
Multi-Timeframe AI-Scored Momentum
```

Market:

- Binance spot
- Long-only in v0.1
- BTCUSDT, ETHUSDT, SOLUSDT

Candidate buy logic:

- 4h trend is not clearly bearish.
- 1h confirms momentum or breakout.
- 15m provides entry trigger.
- Volume or volatility confirms the move.
- Cooldown rules are satisfied.

Candidate exit logic:

- ATR or structure-based stop.
- Trailing stop after favorable movement.
- Trend invalidation.
- Time stop if the trade fails to progress.
- Forced exit only when configured and safe.

### 4.4 AI Scoring Engine

Responsibilities:

- Score rule-generated trade candidates from 0-100.
- Return structured JSON.
- Explain the signal quality.
- Identify market regime and risk flags.
- Log raw AI output for later audit.

AI score policy:

```text
score >= 75: allow normal size
score 60-74: allow reduced size
score 50-59: record only, no trade
score < 50: reject
AI timeout/error: reject or rule-only reduced mode depending on risk state
```

AI cannot:

- Generate independent buy/sell orders.
- Modify hard risk limits.
- Increase size above RiskEngine limits.
- Trade during data or system abnormalities.

### 4.5 Risk Engine

Responsibilities:

- Apply hard pre-trade risk checks.
- Calculate dynamic risk thresholds from current equity and RiskProfile.
- Maintain risk states.
- Block trades that violate account, symbol, order, data, or system constraints.

Risk states:

```text
normal
degraded
no_new_positions
global_pause
emergency_stop
```

### 4.6 Position Sizer

Responsibilities:

- Convert approved trade candidates into target order size.
- Use account equity, max trade risk, ATR, AI score, and RiskEngine size multiplier.
- Enforce single-symbol and total portfolio caps.
- Enforce Binance minimum order size.

### 4.7 Execution Gate

Modes:

```text
paused
paper_auto
live_shadow
live_small_auto
```

Default:

```text
paper_auto
```

The system must not allow direct transition from `paused` to `live_small_auto`.

### 4.8 Paper Executor

Responsibilities:

- Simulate orders and fills.
- Include fees and slippage.
- Update portfolio state.
- Store orders, fills, and position changes.
- Send Telegram notifications.

### 4.9 Portfolio Service

Responsibilities:

- Track cash, positions, average entry, realized PnL, unrealized PnL, fees, total equity, and drawdown.
- Generate portfolio snapshots.

### 4.10 Dashboard

The dashboard is a local web control room. It must prioritize safety, explainability, and traceability.

Layout direction:

- Overview: Trading Control Room
- Signals: AI Strategy Lab
- Analytics: Performance Review

Core pages:

- Overview
- Signals
- Orders
- Risk
- Analytics
- Extensions
- Logs
- Settings

### 4.11 Telegram Notifier

Must notify:

- System start/stop
- Mode changes
- Trade candidates
- AI scores
- Risk rejection
- Paper fills
- Live shadow plans
- Live order status later
- Risk state changes
- API/data errors
- Kill Switch activation
- Daily summaries

### 4.12 Storage

First version uses SQLite.

Core tables:

- `candles`
- `features`
- `signals`
- `ai_scores`
- `risk_decisions`
- `orders`
- `fills`
- `positions`
- `portfolio_snapshots`
- `events`
- `settings`
- `runtime_state`

### 4.13 Runtime Orchestrator

Responsibilities:

- Load configuration.
- Validate API keys.
- Initialize database.
- Backfill candles.
- Run the periodic loop.
- Trigger market data, features, strategy, AI, risk, execution, storage, notification, and dashboard updates.
- Recover safely after restart.

## 5. Extension Templates

v0.1 includes disabled templates for later expansion. These templates define interfaces and metadata only. They do not run live logic.

Templates:

- `FuturesMomentumTemplate`
- `OrderBookImbalanceTemplate`
- `CrossExchangeArbitrageTemplate`
- `NewsSentimentTemplate`
- `OnchainFlowTemplate`
- `MLSignalTemplate`

Default state:

```text
enabled = false
live_trading_allowed = false
status = disabled
```

The dashboard includes an Extensions page with:

- Module name
- Status
- Required data
- Risk level
- Enabled mode
- Reason disabled
- Next milestone

## 6. Dynamic Risk Profiles

Risk limits are based on current account equity, not fixed USDT amounts.

Daily PnL basis:

```text
day_start_equity = equity recorded at daily reset
current_equity = cash + position market value
daily_pnl_pct = (current_equity - day_start_equity) / day_start_equity
```

Small-capital default profile:

```text
profile = small_balanced
equity range = 0-1000 USDT
daily_loss_caution_pct = 5
daily_loss_no_new_positions_pct = 7
daily_loss_global_pause_pct = 10
max_trade_risk_pct = 1.5
max_trade_risk_hard_cap_pct = 2.0
max_symbol_position_pct = 30
max_total_position_pct = 70
```

Medium profile:

```text
profile = medium_conservative
equity range = 1000-10000 USDT
daily_loss_caution_pct = 3
daily_loss_no_new_positions_pct = 5
daily_loss_global_pause_pct = 7
max_trade_risk_pct = 1.0
max_symbol_position_pct = 25
max_total_position_pct = 60
```

Large profile:

```text
profile = large_conservative
equity range = 10000+ USDT
daily_loss_caution_pct = 2
daily_loss_no_new_positions_pct = 4
daily_loss_global_pause_pct = 5
max_trade_risk_pct = 0.5
max_symbol_position_pct = 20
max_total_position_pct = 50
```

Risk tightening policy:

```text
auto_tighten_risk = true
auto_loosen_risk = false
```

When capital grows, the system may automatically tighten risk. When capital shrinks, the system must not automatically loosen risk without user confirmation.

## 7. Circuit Breakers

Circuit breakers are graded. Small issues degrade the system; serious issues pause new positions; critical issues globally pause or emergency stop.

### Level 1: Degraded

Examples:

- AI fails once or twice.
- Telegram fails.
- A single symbol has short data delay.
- One trade has high slippage.
- Two consecutive losing trades.

Actions:

- Continue running.
- Reduce size.
- Increase AI threshold.
- Increase cooldown.
- Mark Dashboard yellow.

### Level 2: No New Positions

Examples:

- Daily loss reaches 7% under small profile.
- Exchange API fails repeatedly.
- Data delay exceeds threshold.
- Order state sync is uncertain.
- Three consecutive losses.

Actions:

- Stop opening new positions.
- Continue managing existing positions.
- Continue market observation.
- Continue shadow signal logging.
- Mark Dashboard orange.

### Level 3: Global Pause

Examples:

- Daily loss reaches 10% under small profile.
- Order status is unknown.
- Database writes fail persistently.
- Severe market data outage.
- Kill Switch is activated.

Actions:

- Stop strategy execution.
- Stop new orders.
- Preserve market data, logs, Dashboard, and Telegram.
- Require user review before resuming.
- Mark Dashboard red.

Emergency exit is configurable:

```text
emergency_exit_enabled = false by default
```

For spot trading, global pause does not automatically force liquidation unless configured.

## 8. Runtime Modes and Live Unlock

### paused

- No new orders.
- Optional market data collection.
- Used for maintenance and debugging.

### paper_auto

- Real market data.
- Automatic strategy, AI, risk, paper execution.
- Full logging and Telegram notification.
- Default first mode.

### live_shadow

- Generate real order plans.
- Do not send orders to Binance.
- Estimate realistic fills and slippage.
- Compare paper fills with likely live execution.

### live_small_auto

- Real Binance spot orders.
- Whitelisted symbols only.
- Small capital only.
- Must pass all RiskEngine checks.
- Requires live trading double lock.

Live unlock requirements:

- `paper_auto` runs continuously for at least 14 days.
- At least 50 candidate signals.
- At least 20 paper orders.
- Maximum drawdown no worse than 12%.
- No system error causes an incorrect order.
- Data outage handling verified.
- RiskEngine rejection behavior verified.
- Telegram verified.
- Dashboard Kill Switch tested.
- `live_shadow` runs at least 7 days.
- Shadow slippage is acceptable.

Live lock:

```yaml
trade_mode: paper_auto
live_trading_enabled: false
live_capital_cap_usdt: 500
require_manual_unlock: true
```

## 9. Dashboard Design

The dashboard should borrow from mature quantitative trading dashboards but focus on this system's unique needs: AI scoring, risk explanation, and safe operation.

Reference direction:

- Hummingbot-style strategy and deployment management
- FreqUI-style bot monitoring and trade controls
- freqdash-style portfolio and performance visibility

Final direction:

- Home page: Trading Control Room
- Signals page: AI Strategy Lab
- Analytics page: Performance Review

Overview page:

- Current mode
- Current risk state
- Current risk profile
- Account equity
- Today PnL
- Drawdown
- Positions
- Recent orders
- Recent risk events
- Kill Switch

Signals page:

- Rule strategy signal
- Rule confidence
- AI score
- Market regime
- Risk flags
- Risk result
- Size multiplier
- Reject reasons
- AI explanation
- Similar historical signal outcomes

Risk page:

- Account equity
- Risk profile
- 5%, 7%, 10% thresholds converted to USDT under small profile
- Consecutive loss state
- Max trade risk
- Symbol exposure
- Total exposure
- Cooldowns
- Auto-tighten status
- Auto-loosen disabled status

Analytics page:

- Equity curve
- Drawdown curve
- Win rate
- Profit factor
- Fees
- Slippage
- Symbol-level performance
- AI score versus trade outcome
- Rejected signal shadow performance
- Paper versus live shadow comparison

## 10. Technical Stack

Backend:

- Python 3.11+
- FastAPI
- SQLite
- SQLAlchemy
- Pydantic
- APScheduler or asyncio loop
- ccxt or Binance official connector
- pandas
- numpy
- pandas-ta or ta
- httpx
- python-telegram-bot

AI:

- OpenAI API or compatible LLM API
- Structured JSON output
- Timeout and retry controls
- Failure downgrade logic
- Raw response audit logs

Dashboard:

- React + Vite
- Lightweight CSS or Tailwind
- Recharts / Lightweight Charts
- REST API first
- WebSocket later if needed

Local runtime:

- `uvicorn` for backend
- Vite dev server for dashboard
- SQLite file database
- `.env` and YAML config

Future deployment:

- Docker
- Optional Postgres
- systemd or Docker Compose
- Health checks
- Log rotation
- Remote Telegram alerts

## 11. Project Structure

```text
crypto-ai-trader/
  README.md
  .env.example
  config/
    app.yaml
    risk_profiles.yaml
    strategies.yaml
    exchanges.yaml
  research/
    backtests/
    notebooks/
    reports/
  trading/
    main.py
    runtime/
    market_data/
    features/
    strategies/
      base.py
      active/
      templates/
    ai/
    risk/
    portfolio/
    execution/
    notifications/
    storage/
    dashboard_api/
  dashboard/
    src/
      pages/
      components/
      api/
  tests/
    unit/
    integration/
  docs/
    architecture/
    operations/
    superpowers/
      specs/
```

## 12. Development Milestones

### Milestone 0: Project Skeleton

- Project directories
- Config files
- `.env.example`
- SQLite initialization
- Basic logging
- Start command

Acceptance:

- Backend starts locally.
- Empty dashboard opens.
- Events can be written to the database.

### Milestone 1: Market Data

- Binance candle fetcher
- 15m, 1h, 4h candles
- Candle persistence
- Data quality checks
- Dashboard data status

Acceptance:

- BTC/ETH/SOL data writes consistently.
- Delayed or missing data triggers events.

### Milestone 2: Strategy and Features

- Indicator calculations
- Multi-timeframe momentum strategy
- Candidate signal creation
- Signals page display

Acceptance:

- Candidate trades are generated.
- Rule reasons are traceable.
- No order is sent directly by strategy.

### Milestone 3: AI Scoring

- AI JSON schema
- Candidate scoring
- Timeout and failure handling
- Raw response storage

Acceptance:

- Candidate signals receive AI scores.
- AI failure does not crash runtime.

### Milestone 4: Risk and Position Sizing

- RiskProfile system
- Dynamic equity thresholds
- 5/7/10 small-profile daily loss levels
- Consecutive loss controls
- Circuit breaker state machine
- Position sizing

Acceptance:

- High-risk trades are rejected.
- Dashboard shows current risk thresholds in both percent and USDT.
- Kill Switch works.

### Milestone 5: Paper Execution

- PaperExecutor
- Fees and slippage
- Orders, fills, positions
- Portfolio snapshots
- Telegram notifications

Acceptance:

- Full paper loop works: signal -> AI -> risk -> paper order -> position -> dashboard.

### Milestone 6: Complete Dashboard

- Overview
- Signals
- Orders
- Risk
- Analytics
- Extensions
- Logs
- Settings

Acceptance:

- User can understand system state quickly.
- User can see why a trade was approved or rejected.
- User can pause the system.

### Milestone 7: Live Shadow

- Real order plan generation
- No real order submission
- Estimated live fill and slippage
- Paper versus shadow comparison

Acceptance:

- Paper fill assumptions can be validated against realistic live execution.

### Milestone 8: Live Small Auto

- Binance spot live executor
- Double live lock
- Capital cap
- Order state sync
- Restart recovery

Acceptance:

- Small-capital live automatic spot trading works without duplicate orders.
- Abnormal state pauses and notifies.

## 13. Testing Strategy

Unit tests:

- Indicators
- Strategy conditions
- AI schema validation
- Risk thresholds
- Position sizing
- Circuit breaker state transitions

Integration tests:

- Market data to signal
- Signal to AI score
- AI score to risk decision
- Risk decision to paper order
- Kill Switch
- AI failure downgrade
- Data delay behavior

Replay tests:

- Historical candle replay through the full runtime.
- Expected orders, risk states, and portfolio snapshots are checked.

Manual acceptance:

- Dashboard pages
- Telegram notifications
- Mode switching
- Kill Switch
- Restart recovery

## 14. Explicit Non-Goals for v0.1

v0.1 will not implement:

- Real futures trading
- High-frequency order book strategies
- Market making
- Cross-exchange arbitrage
- News or social media trading
- On-chain signal ingestion
- ML model training pipeline
- Automatic parameter evolution
- Large-capital live automation

These remain as disabled extension templates and roadmap items.

## 15. Open Implementation Notes

Implementation should start with Milestones 0-5, then complete Dashboard polish in Milestone 6. `live_shadow` and `live_small_auto` should not start until the paper trading loop is stable and observable.

The safest first build target is:

```text
Milestone 0 -> Milestone 5
```

Then:

```text
Milestone 6 -> Milestone 7 -> Milestone 8
```

This keeps real money risk out of the early engineering phase while still designing the system for eventual small-capital automatic live trading.
