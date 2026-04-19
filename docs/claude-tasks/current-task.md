# Claude Code Task: Runtime Ops Hardening (24/7 Local Reliability, Paper-Only)

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Harden local runtime operations for long-running paper trading:

- safer process lifecycle
- restart visibility and recovery metadata
- better operational observability
- one-command local reliability checks

This is an ops-hardening milestone, not a strategy or live-trading milestone.

## Read First

- `/Users/zihanma/Desktop/crypto-ai-trader/trading/runtime/runner.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/runtime/supervisor.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/runtime/cli.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/storage/repositories.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/dashboard_api/routes_runtime.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/Makefile`
- `/Users/zihanma/Desktop/crypto-ai-trader/README.md`

## Required Scope

### 1) Supervisor heartbeat + liveness metadata

Enhance supervisor visibility so operators can tell if runtime is genuinely alive:

- Add periodic supervisor heartbeat event (e.g. every 60s) while loops are running.
- Heartbeat event should include:
  - ingest thread alive flag
  - trading thread alive flag
  - uptime seconds
  - active symbols
- Ensure heartbeat stops cleanly when supervisor exits.

### 2) Runtime restart/recovery markers

Add minimal, deterministic restart metadata events:

- On supervisor start, record a `runtime_boot` event with:
  - startup timestamp (UTC)
  - process mode (`supervisor`)
  - configured intervals
- On supervisor stop, include total uptime in `supervisor_stopped` context.
- If a component crashes, include crash marker with component + exception type + message.

### 3) Runtime status API enhancement (read-only)

Extend `/runtime/status` response with operational fields (safe defaults when absent):

- `supervisor_alive` (bool | null)
- `ingestion_thread_alive` (bool | null)
- `trading_thread_alive` (bool | null)
- `uptime_seconds` (int | null)
- `last_heartbeat_time` (iso | null)
- `last_component_error` (string | null)

Do not break existing fields consumed by dashboard.

### 4) Dashboard Overview runtime card enhancement

On Overview page runtime section, display the new operational fields:

- alive/degraded indicator
- uptime
- last heartbeat time
- last component error

Maintain existing partial-failure behavior:

- per-endpoint failure flags
- placeholders only for failed panels
- successful panels keep real data

### 5) Local ops command set

Add Makefile helpers for operator workflow:

- `make runtime-supervisor` (already exists; keep)
- `make runtime-health`:
  - curl health, runtime status, risk status endpoints
  - concise output
- `make runtime-tail-events`:
  - print recent runtime/supervisor/ingestion events (read-only DB query via existing Python modules)

### 6) Docs update

Update README with a short “24/7 Local Ops” section:

- how to start supervisor
- how to run runtime-health checks
- how to inspect recent events
- expected healthy signals (heartbeat freshness, thread alive flags)

## Safety Constraints (strict)

- No live trading implementation.
- No private Binance API integration.
- No API key handling changes.
- No order execution endpoint.
- No bypass of RiskEngine / execution safety boundaries.

## Tests (required)

Add/extend tests to cover:

1. supervisor heartbeat event emission
2. runtime status includes new fields with safe defaults
3. runtime status reflects heartbeat and component error paths
4. dashboard build remains passing

Prefer focused tests in:

- `tests/unit/test_runtime_supervisor.py`
- `tests/integration/test_runtime_status_api.py`

## Verification (required)

Run exactly:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/ruff check .
.venv/bin/pytest -q
cd /Users/zihanma/Desktop/crypto-ai-trader/dashboard
npm run build
cd /Users/zihanma/Desktop/crypto-ai-trader
git status --short
```

## Commit

If verification passes:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
git add trading/runtime trading/dashboard_api dashboard/src Makefile README.md tests docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: harden local runtime ops observability and health checks"
```

## Completion Report

Write `/Users/zihanma/Desktop/crypto-ai-trader/docs/claude-tasks/last-result.md` with:

- Task
- Status
- Files changed
- Verification summary
- Commit hash
- Safety checklist

Then stop.
