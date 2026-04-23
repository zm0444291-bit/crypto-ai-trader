# CLAUDE.md

>This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local-first AI-assisted cryptocurrency quantitative trading system for **paper trading only** on Binance spot. Live trading is explicitly locked until future milestones implement and review required safety features.

**Default settings**: 500 USDT initial cash, BTCUSDT/ETHUSDT/SOLUSDT, 15m candles, 300s cycle intervals.

---

## 开发计划（v3）

完整开发计划在 `docs/superpowers/plans/2026-04-21-v3-final-plan.md`。所有开发工作必须按该计划执行，每个 Stage 完成后必须通过对应的 **Review Checklist** 才能合并到 main 分支。

### Stage 依赖图（关键路径）

```
Stage 0 → Stage 1 → Stage 2/2b → Stage 5 → Stage 3 → Stage 9 → Stage 10
                          ↓
              可并行: Stage 4, Stage 6, Stage 7, Stage 8
```

### Stage 清单

| Stage | 名称 | 主要交付物 | 关键文件/目录 |
|-------|------|-----------|-------------|
| 0 | 安全修复 | 敏感信息扫描 + DB 事务加固 | `scripts/scan_secrets.py`, `trading/storage/` |
| 1 | 退出策略 100% | ExitEngine 重构，YAML 配置化 | `trading/strategies/exits/`, `config/exit_strategies.yaml` |
| 2 | 回测框架 + 因子库 | BacktestEngine + 10+ 因子 | `trading/backtest/`, `trading/features/` |
| 2b | 数据迁移 + Schema | 新增字段迁移脚本 | `scripts/migrate_*.py`, `trading/storage/models.py` |
| 3 | 策略多元化 | 3 种策略 + 状态机 | `trading/strategies/`, `trading/strategies/factory.py` |
| 4 | Dashboard WebSocket | 实时数据推送 | `trading/dashboard_api/ws_manager.py`, `dashboard/src/` |
| 5 | 风控链路 100% | 风控引擎完善 + 冻结机制 | `trading/risk/`, `trading/execution/gate.py` |
| 6 | 通知系统 100% | 审批流 + 通知队列 | `trading/notifications/` |
| 7 | 24/7 运维体系 | AutoHealer + RestartLoopDetector + structured logging | `trading/runtime/healer.py`, `trading/logging/`, `scripts/macos_launchd_runtime.sh` |
| 8 | 测试 100% + 文档 | 覆盖率 ≥ 85%，用户手册 | `tests/`, `docs/user-manual.md`, `docs/runbook-*.md` |
| 9 | 实盘解锁评审 | 12 项前置条件 + 压力测试 | `docs/live-trading-readiness-report.md` |
| 10 | 实盘灰度 | 小资金实盘（小 < 100 USDT） | `config/live-minimal.yaml`, `trading/runtime/state.py` |

### 代码审查机制（CR）

每个 Stage 的 PR 必须通过以下审查：

- **CR-1 自动化检查**：类型检查（mypy --strict）+ 代码风格（ruff）+ 单元测试 + 覆盖率门控
- **CR-2 Human Review**：Owner 逐项检查 Review Checklist（逻辑正确性、边界情况、风险评估）
- **CR-3 覆盖率门控**：核心模块 ≥ 95%，高风险 ≥ 90%，中等 ≥ 85%，辅助 ≥ 80%

### PR 标题格式

```
[Stage-N] 任务描述
例: [Stage-1] 退出策略 YAML 配置化
```

### 覆盖率要求

| 模块 | 覆盖率要求 |
|------|-----------|
| `trading/execution/` | ≥ 95% |
| `trading/risk/` | ≥ 95% |
| `trading/strategies/exits/` | ≥ 95% |
| `trading/runtime/paper_cycle.py` | ≥ 95% |
| `trading/notifications/approval/` | ≥ 90% |
| `trading/runtime/healer/` | ≥ 90% |
| `trading/features/` | ≥ 85% |
| 项目整体 | ≥ 85% |

---

## Architecture

```
trading/
├── main.py                  # FastAPI app entry point
├── runtime/                 # Trading runtime engine
│   ├── cli.py               # CLI entry: --once, --interval, --supervisor
│   ├── runner.py            # Single-cycle and loop runner
│   ├── supervisor.py        # Concurrent ingest+trade loops with heartbeat monitoring
│   ├── paper_cycle.py       # Core 11-stage trading pipeline
│   ├── config.py            # AppSettings (Pydantic BaseSettings, env-backed)
│   └── state.py             # Runtime mode (paused/paper_auto/live_shadow/live_small_auto)
├── strategies/              # Strategy candidates
│   └── active/multi_timeframe_momentum.py  # Only active strategy
├── features/                # Technical indicators and feature builder
├── ai/                      # AI scoring abstraction
│   ├── scorer.py            # AIScorer (fail-closed on errors)
│   ├── http_client.py       # Generic HTTP AI scorer client
│   └── minimax_client.py    # MiniMax-specific AI scorer
├── execution/               # Order execution
│   ├── paper_executor.py    # Simulated market buy with fee/slippage
│   └── gate.py              # ExecutionGate: mode-aware routing (paper/shadow/blocked)
├── risk/                    # Risk management
│   ├── profiles.py          # 3-tier risk profiles by equity level
│   ├── pre_trade.py         # Pre-trade risk checks
│   ├── position_sizing.py   # Kelly-based position sizing
│   └── state.py             # Runtime risk state
├── market_data/             # Data ingestion
│   ├── binance_client.py    # Binance API client
│   ├── candle_service.py    # Candle aggregation service
│   └── ingestion_runner.py  # Ingestion loop
├── storage/                 # Persistence
│   ├── db.py                # SQLAlchemy engine, session factory, init_db
│   ├── models.py            # ORM models: Event, Candle, Order, Fill, RuntimeControl, ShadowExecution
│   └── repositories.py      # Data access layer
├── notifications/           # Alerting
│   ├── telegram_notifier.py # Telegram push notifications
│   ├── log_notifier.py      # Logger-based fallback notifier
│   └── dedup.py             # Alert deduplication (5-min window)
├── portfolio/               # Portfolio accounting
│   └── accounting.py        # PortfolioAccount: positions, equity, PnL
├── dashboard_api/           # FastAPI routes for dashboard
│   ├── routes_health.py     # /health
│   ├── routes_runtime.py     # /runtime/status, /runtime/control
│   ├── routes_risk.py        # /risk/status
│   ├── routes_portfolio.py   # /portfolio/status
│   ├── routes_orders.py      # /orders
│   ├── routes_market_data.py # /market-data/candles
│   ├── routes_analytics.py   # /analytics/*
│   └── routes_events.py      # /events
│
dashboard/                   # React + Vite dashboard
├── src/App.tsx              # React Router with 8 pages: Overview, Signals, Orders, Risk, Analytics, Extensions, Logs, Settings
└── src/api/client.ts        # API client for backend

config/
├── strategies.yaml           # Strategy enable/disable and symbol config
└── risk_profiles.yaml       # Risk profile tiers (small_balanced, medium_conservative, large_conservative)
```

## Core Pipeline (paper_cycle.py stages)

1. Fetch candles (15m/1h/4h) → 2. Build features (RSI, EMA, ATR, trend) → 3. Generate candidate via strategy → 4. AI scoring (fail-closed) → 5. Pre-trade risk check → 6. Position sizing → 7. Execution gate → 8. Paper execution → 9. Persist order/fill → 10. Record events

## Key Safety Mechanisms

- **ExecutionGate** (`trading/execution/gate.py`): Mode-aware router. `live_small_auto` is hard-blocked. `kill_switch` always blocks. `live_trading_lock` blocks live modes only.
- **Fail-closed AI scoring**: `AIScorer.score_candidate()` returns `decision_hint=reject, ai_score=0` on any client error.
- **Risk profiles**: Equity-tiered (small/medium/large) with daily loss thresholds that pause or prohibit new positions.
- **Alert deduplication**: 5-minute window prevents notification spam.

## Common Commands

```bash
# Setup
make install              # Create .venv + pip install -e ".[dev]"
make db-init             # Initialize SQLite DB

# Run
make backend             # FastAPI on http://127.0.0.1:8000
make dashboard           # Vite on http://localhost:5173

# Runtime
make runtime-once                       # Single cycle
make runtime-supervisor                 # Concurrent ingest + trade loops (300s intervals)
make runtime-supervisor INGEST_INTERVAL=120 TRADE_INTERVAL=60  # Custom intervals
make runtime-health                     # Curl health + runtime status + risk status

# Development
make check             # ruff lint + pytest
make lint              # ruff check only
make test              # pytest -q
pytest tests/unit/test_paper_cycle.py -v   # Single test file

# macOS 24/7
make runtime-agent-install   # Install LaunchAgent
make runtime-agent-status    # Check status
make runtime-agent-logs      # View logs

# Config
export AI_SCORING_BACKEND=minimax
export MINIMAX_API_KEY=...
export MINIMAX_BASE_URL=https://api.minimax.io/v1
export MINIMAX_MODEL=MiniMax-M2.7
make runtime-minimax-smoke   # Test AI scorer connectivity
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_SCORING_BACKEND` | `http` | `http` or `minimax` |
| `AI_SCORING_URL` | — | Remote AI scorer endpoint |
| `AI_SCORING_TIMEOUT` | `30` | Scoring timeout in seconds |
| `MINIMAX_API_KEY` | — | MiniMax API key |
| `MINIMAX_BASE_URL` | `https://api.minimax.io/v1` | MiniMax endpoint |
| `MINIMAX_MODEL` | `MiniMax-M2.7` | MiniMax model name |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID |
| `DATABASE_URL` | `sqlite:///./data/crypto_ai_trader.sqlite3` | SQLite path |
| `BACKEND_PORT` | `8000` | Backend API port |

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, httpx
- **Dashboard**: React 18, TypeScript, React Router, Vite
- **Database**: SQLite (file-based, at `data/crypto_ai_trader.sqlite3`)
- **Testing**: pytest, pytest-cov
- **Linting**: ruff

## Testing

Tests are in `tests/unit/` and `tests/integration/`. Integration tests hit the real DB. Unit tests use mocks. Run with `make test` or `pytest tests/ -v`.

## Notes
- The system uses **Decimal** for all financial calculations to avoid float precision issues.
- All times are stored in UTC via `datetime.now(UTC)`.
- The dashboard CORS whitelist is hardcoded to `http://127.0.0.1:5173` and `http://localhost:5173` — use these exact URLs.
- The 24/7 LaunchAgent (`scripts/macos_launchd_runtime.sh`) reads `.env` for environment variables.

---

## Forex/Gold Migration

The system is being migrated from Binance crypto spot to **IBKR + Pepperstone** for gold/forex trading.

### New Architecture

```
trading/market_data/adapters/
├── __init__.py          # Exports: create_ibkr_adapter, create_pepperstone_adapter, BidAskQuote
├── base.py              # MarketDataAdapter ABC + BidAskQuote dataclass
├── ibkr_adapter.py     # IBKR TWS API via ib_insync + MockIBKRAdapter fallback
└── pepperstone_adapter.py  # Pepperstone REST API + MockPepperstoneAdapter fallback

trading/events/
└── economic_calendar.py  # NFP/CPI/FOMC block trading, market hours enforcement

config/
├── contracts.yaml       # XAUUSD (100oz, $10/point), EURUSD specs
├── broker.yaml         # IBKR/Pepperstone API config templates
└── strategy_params_forex.yaml  # EMA 21/50, RSI 35/65, ATR 2.5x stop
```

### Key Design Decisions

- **Adapter pattern**: `MarketDataAdapter` ABC unifies IBKR and Pepperstone. Mock adapters enable testing without API keys.
- **Bid/Ask pricing**: `BidAskQuote` dataclass replaces bps slippage. BUY uses ask, SELL uses bid.
- **IBKR port**: Paper Trading = 4001, Live = 7496
- **IBKR requires**: TWS or Gateway app running locally on port 4001
- **Pepperstone**: REST API at `https://api.pepperstone.jp/v1`, falls back to mock
- **Economic calendar**: Blocks XAUUSD/EURUSD trading 30min around NFP/FOMC/CPI events

### Pending (requires user action)
1. Register IBKR account, enable Market Data API permissions
2. Run IBKR TWS or Gateway on port 4001
3. Register Pepperstone demo account, get API key
4. Fill `config/broker.yaml` with API credentials
5. Run `git commit` on `forex-migration` branch

### Commands
```bash
git checkout forex-migration
cd ~/Desktop/crypto-ai-trader
.venv/bin/python -m pytest tests/market_data/ tests/unit/test_paper_executor.py tests/events/ -v  # Run tests
```
