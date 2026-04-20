# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local-first AI-assisted cryptocurrency quantitative trading system for **paper trading only** on Binance spot. Live trading is explicitly locked until future milestones implement and review required safety features.

**Default settings**: 500 USDT initial cash, BTCUSDT/ETHUSDT/SOLUSDT, 15m candles, 300s cycle intervals.

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
