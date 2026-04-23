# Crypto AI Trader

Local-first AI-assisted cryptocurrency quantitative trading system.

The first implementation target is automatic paper trading for Binance spot with:

- Medium-frequency 15m/1h signals
- 4h trend context
- AI scoring for rule-generated candidates
- Dynamic risk profiles
- SQLite storage
- Local dashboard API
- Telegram notifications in a later milestone

## Safety

The default mode is paper trading.

Live trading must remain locked until the approved live unlock milestones are implemented and reviewed.

## First Local Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn trading.main:app --reload --host 127.0.0.1 --port 8000
```

## 24/7 Local Ops

Long-running supervisor-based paper trading with operational visibility.

### Start the supervisor

```bash
make runtime-supervisor                          # 5min ingest + trade intervals
make runtime-supervisor INGEST_INTERVAL=120 TRADE_INTERVAL=60  # custom intervals
```

### Run as a macOS LaunchAgent (recommended for 24/7 local)

```bash
# install + start (auto-restart, auto-start on login)
make runtime-agent-install

# inspect and logs
make runtime-agent-status
make runtime-agent-logs

# stop / remove
make runtime-agent-stop
make runtime-agent-uninstall
```

Optional runtime tuning before install:

```bash
INGEST_INTERVAL=120 TRADE_INTERVAL=60 RUNTIME_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT make runtime-agent-install
```

### Health checks

```bash
make runtime-health   # curl health, runtime status, and risk status endpoints
```

Output is operator-friendly and compact — each check prints a short label and a pass/fail summary line, with full JSON available on the API endpoints directly.

**What "healthy" looks like:**

| Check | Healthy signal |
|-------|---------------|
| `/health` | `status: "ok"` |
| `/runtime/status` `supervisor_alive` | `true` — heartbeat within last 2 min |
| `/runtime/status` `ingestion_thread_alive` | `true` |
| `/runtime/status` `trading_thread_alive` | `true` |
| `/runtime/status` `heartbeat_stale_alerting` | `false` — no stale heartbeat |
| `/runtime/status` `restart_exhausted_ingestion` | `false` |
| `/runtime/status` `restart_exhausted_trading` | `false` |

### WebSocket real-time push

The backend pushes real-time events to connected dashboard clients over WebSocket at `ws://127.0.0.1:8000/ws`. Clients subscribe by channel; the server sends all messages on subscribed channels automatically.

**Channels:**

| Channel | Events |
|---------|--------|
| `runtime` | `heartbeat`, `loop_finished`, `cycle_complete` |
| `portfolio` | `portfolio_update` |
| `orders` | `order_update`, `order_fill` |
| `risk` | `risk_update` (risk state changes, position limit warnings) |
| `events` | `execution_gate_blocked`, `risk_rejected` |
| `market` | `kline_update` (Binance real-time klines) |
| `all` | Broadcast to all channels |

**Dashboard WS integration:**
- `Overview.tsx`: subscribes to `market` channel for real-time price ticker; falls back to polling on disconnect
- `Risk.tsx`: subscribes to `risk` channel for instant risk state updates; shows WS connection indicator (green dot = live)
- Connection is shared — multiple tab components use the same WebSocket instance

**Protocol:** `WsMessage { channel, payload, ts }` where `payload` is event-type-specific:

```typescript
// risk_update payload
{ event_type: 'risk_state_changed', risk_state: 'degraded', message: '...', details: {...}, timestamp: '...' }

// kline_update payload
{ symbol: 'BTCUSDT', timeframe: '1m', open: '...', high: '...', low: '...', close: '...', volume: '...' }
```

The frontend `useWebSocket` hook (`src/api/ws.ts`) handles auto-reconnect (3 s delay), channel filtering, and shared singleton connection across components.

### Inspect recent events

```bash
make runtime-tail-events   # last 30 events from the DB

# with filters
python -m trading.runtime.event_tail --limit 10 --severity error
python -m trading.runtime.event_tail --component supervisor --limit 50
python -m trading.runtime.event_tail --event-type cycle_error
```

### Stop the supervisor

Press `Ctrl+C` — the supervisor handles shutdown cleanly, sets the stop event, waits for both loops, and records `supervisor_stopped` with uptime.

### Common failures and first-action checklist

| Symptom | First action |
|---------|-------------|
| `supervisor_alive: false` | Check that the supervisor process is still running; re-run `make runtime-supervisor` |
| `ingestion_thread_alive: false` | Run `make db-init` then restart supervisor |
| `trading_thread_alive: false` | Check Telegram/AI scorer env vars; try `make runtime-once` for a single cycle |
| `restart_exhausted_ingestion` or `restart_exhausted_trading` is `true` | Component exhausted; investigate root cause before restart |
| `/risk/status` returns 500 | Run `make db-init` to ensure DB schema is current |
| Dashboard shows stale data | Backend may be down; verify with `curl http://127.0.0.1:8000/health` |
| Many `cycle_error` events | Run `make runtime-once` manually to see cycle-level error output |

### Runtime heartbeat

Every 60 seconds while running, the supervisor records a `supervisor_heartbeat` event containing:
- `ingest_thread_alive` / `trading_thread_alive` flags
- `uptime_seconds` since supervisor start
- `symbols` being traded

### 24-hour paper soak checklist

Run this once after major changes:

```bash
make runtime-agent-install
make backend
```

Then check every few hours:
- `/runtime/status` keeps `supervisor_alive=true`
- `heartbeat_stale_alerting=false`
- `restart_exhausted_ingestion=false`
- `restart_exhausted_trading=false`
- Dashboard keeps refreshing without persistent offline/degraded state

## Local Paper Trading Quickstart

This system runs **paper trading only** — no real funds are used. All trading is simulated against live market data.

### 1. Install dependencies

```bash
make install
```

This creates a virtual environment (`.venv`) and installs all dependencies.

### 2. Initialize the database

```bash
make db-init
```

Creates `data/crypto_ai_trader.sqlite3` (SQLite) and runs all migrations. Safe to re-run.

### 3. Start services

Open two terminal tabs:

**One-command local start + healthcheck (recommended):**
```bash
./scripts/start_local_stack.sh
```
This starts backend + dashboard (if not running), checks `/health`, `/runtime/status`, `/runtime/control-plane`, `/runtime/release-gate/live`, and opens the dashboard automatically.

**Tab 1 — Backend API + Dashboard (concurrent):**
```bash
make backend   # FastAPI on http://127.0.0.1:8000
make dashboard # Vite on http://localhost:5173 (in a second terminal)
```

**Tab 2 — Runtime:**
```bash
make runtime-once                      # run one cycle and exit
make runtime-supervisor                 # run ingestion + trading loops concurrently (preferred, 300s intervals)
make runtime-supervisor INGEST_INTERVAL=120 TRADE_INTERVAL=60  # custom intervals
```

Override symbols: `make runtime-supervisor RUNTIME_SYMBOLS=BTCUSDT,ETHUSDT`

### 4. Health checks

- Backend API: `curl http://127.0.0.1:8000/health`
- Dashboard: open `http://localhost:5173` — panels should populate after first runtime cycle
- Runtime: check `http://127.0.0.1:8000/runtime/status`

### 5. Known safe defaults

| Setting | Value |
|---------|-------|
| Mode | Paper only (no live trading) |
| Initial cash | 500 USDT |
| Symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| Candle interval | 15m |
| Database | SQLite at `data/crypto_ai_trader.sqlite3` |
| Supervisor ingest interval | 300s |
| Supervisor trade interval | 300s |

### Live release gate (preflight only)

Before any `live_small_auto` attempt, run:

```bash
./scripts/release_gate_live.sh --api-url http://127.0.0.1:8000 --symbol BTCUSDT
```

**Structured output (JSON):** for dashboard or CI/CD consumption:

```bash
./scripts/release_gate_live.sh --format json --output gate.json
cat gate.json
```

What it checks:
- `ruff`, `pytest`, dashboard build
- Backend `/health` and `/runtime/control-plane` connectivity
- `live_small_auto` dry-run preflight (`dry_run=true`) with your symbol
- Missing-symbol dry-run rejection (`preflight:symbol_required`)
- `ExecutionGate` still blocks `live_small_auto` by default

If any check fails, the script exits non-zero and prints the blocking reason.

**Flags:** `--format text|json` (default: text), `--output <path>` (write to file), `--quiet` (suppress text output), `--dry-run` (no-op, backwards compatibility).

**JSON output** includes: `generated_at`, `mode`, `summary { pass, allow_live_shadow, allow_live_small_auto_dry_run, blocked_reasons }`, `checks[] { code, status, message }`, and `runtime_snapshot { trade_mode, lock_enabled, transition_guard_to_live_small_auto, risk_state, heartbeat_stale_alerting }`.

### Telegram alerts (optional)

If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, cycle errors and risk events are sent to Telegram. Without them the system logs to Python logger and continues normally.

```bash
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
make runtime-supervisor
```

### AI scoring (optional)

By default (`AI_SCORING_BACKEND=http`), if `AI_SCORING_URL` is set, the runtime uses a remote AI scorer to evaluate candidates. When the URL is absent, scoring fails closed (all candidates rejected) — the cycle continues but no trades are executed.

```bash
export AI_SCORING_BACKEND=http
export AI_SCORING_URL=https://your-ai-service.example.com/score
export AI_SCORING_TIMEOUT=30
make runtime-supervisor
```

MiniMax integration (OpenAI-compatible API):

```bash
export AI_SCORING_BACKEND=minimax
export MINIMAX_API_KEY=your_minimax_api_key
# Global endpoint (international): https://api.minimax.io/v1
# Mainland China endpoint:        https://api.minimaxi.com/v1
export MINIMAX_BASE_URL=https://api.minimax.io/v1
export MINIMAX_MODEL=MiniMax-M2.7
export MINIMAX_TIMEOUT=30
make runtime-minimax-smoke
make runtime-supervisor
```

If you use launchd (`make runtime-agent-install`), put the same variables in project `.env` so the agent process can load them.

## Troubleshooting

### Dashboard shows "offline" or CORS errors

The backend CORS whitelist is set to `http://127.0.0.1:5173` and `http://localhost:5173`. If you access the dashboard on a different port or hostname, the API requests are blocked.

Fix: Use the exact URL shown in the Vite output — both `http://127.0.0.1:5173` and `http://localhost:5173` are valid origins as long as they match what Vite printed at startup.

### Port conflicts (8000 or 5173 already in use)

Check what is using the port:

```bash
# macOS
lsof -i :8000
lsof -i :5173
```

Override the default port:

```bash
make backend BACKEND_PORT=8001
# Then set VITE_API_BASE_URL=http://localhost:8001 in dashboard tab
make dashboard
```

### Telegram notifications not working

1. Verify env vars are set:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```
2. Test the bot directly: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser
3. If the bot is silent, the runtime logs a warning — check Python logger output for `trading.alerts.telegram`
4. Missing env vars are **not errors** — the system falls back to logger-only notifications automatically

### Database locked or missing

If you see SQLite errors, ensure the process writing to the DB is not running multiple instances simultaneously. The runtime loop and backend can both access the same DB file concurrently (SQLite handles this), but running two loops at once can cause locking.

### Runtime cycle throws "cycle_error" immediately

Check:
1. Market data: the cycle needs recent 15m candles in the DB. If the DB is brand new, run `make runtime-once` a few times to pull in data.
2. AI scorer backend: default runtime scorer is HTTP-based (`AI_SCORING_BACKEND=http`) and fails closed when `AI_SCORING_URL` is missing/unreachable. This is expected and keeps paper runtime safe.
