# Runbook: Paper-Safe Operations

> **Scope**: This runbook covers 24/7 paper-safe operation of the crypto-ai-trader.
> All instructions assume `paper_auto` mode with no real capital at risk.
> **Live execution is disabled and blocked by design.**

---

## Table of Contents

1. [Pre-Launch Checklist](#1-pre-launch-checklist)
2. [Runtime Inspection](#2-runtime-inspection)
3. [Fault Classification & Response](#3-fault-classification--response)
4. [Recovery Procedure](#4-recovery-procedure)
5. [Forbidden Operations](#5-forbidden-operations)
6. [Rollback & Safe Shutdown](#6-rollback--safe-shutdown)

---

## 1. Pre-Launch Checklist

Complete these checks **before** starting the runtime for the first time or after any configuration change.

### 1.1 Configuration Files

| Check | Command / Validation | Expected |
|-------|---------------------|---------|
| `default_trade_mode` is NOT `live_small_auto` | `grep default_trade_mode config/app.yaml` | `paper_auto` |
| `live_trading_enabled: false` in app config | `grep live_trading_enabled config/app.yaml` | `false` |
| `live_trading_enabled: false` in exchanges | `grep live_trading_enabled config/exchanges.yaml` | `false` |
| `require_manual_unlock: true` | `grep require_manual_unlock config/app.yaml` | `true` |

### 1.2 Execution Gate (Static)

| Check | How | Expected |
|-------|-----|---------|
| `ExecutionGate` blocks `live_small_auto` by default | `grep live_small_auto_requires_explicit_unlock trading/execution/gate.py` | Match found |
| `LiveTradingLock` default is `enabled=False` | `grep 'enabled: bool = False' trading/execution/gate.py` | Match found |

### 1.3 Database

| Check | Command | Expected |
|-------|---------|---------|
| DB file exists | `ls data/crypto_ai_trader.sqlite3` | File present |
| DB is initialised | `.venv/bin/python -c "from trading.storage.db import create_database_engine, init_db; from trading.runtime.config import AppSettings; engine = create_database_engine(AppSettings().database_url); init_db(engine); print('OK')"` | `OK` |

### 1.4 Mode & Lock State (API)

Start the backend (`make backend`) then verify:

```bash
# Should show paper_auto mode, lock disabled, route=paper
curl -s http://localhost:8000/runtime/control-plane | python3 -m json.tool
```

Expected `control-plane` fields:
- `trade_mode`: `"paper_auto"`
- `lock_enabled`: `false`
- `execution_route`: `"paper"` (never `"live"` or `"shadow"` unless intentionally in `live_shadow` paper mode)

### 1.5 Dependencies

```bash
.venv/bin/ruff check .          # 0 errors
.venv/bin/pytest -q              # all pass
cd dashboard && npm run build    # 0 errors
```

### 1.6 Network Access (Binance)

Paper-safe does **not** require Binance API keys, but must be able to reach public Binance endpoints:

```bash
curl -s --max-time 5 https://api.binance.com/api/v3/ping
# Expected: {}  (or timeout if restricted network — paper-safe works without it via mock data)
```

### 1.7 Structured Gate Output (JSON)

`scripts/release_gate_live.sh` supports `--format json` for machine consumption:

```bash
./scripts/release_gate_live.sh --format json --output /tmp/gate.json
```

The JSON output is self-contained and fail-closed: if any critical dependency is unavailable, `summary.pass=false` and `summary.blocked_reasons` contains human-readable descriptions. See `generated_at`, `summary`, `checks[]`, and `runtime_snapshot` fields in the output.

---

## 2. Runtime Inspection

### 2.1 Health Endpoints

| Endpoint | What to Check |
|----------|---------------|
| `GET /health` | `{"status":"ok"}` |
| `GET /runtime/status` | Full status object (see §2.2) |
| `GET /runtime/control-plane` | Mode, lock, route snapshot |

### 2.2 Runtime Status Fields

All fields from `GET /runtime/status`:

| Field | Healthy | Alert |
|-------|---------|-------|
| `supervisor_alive` | `true` | `false` or `null` |
| `ingestion_thread_alive` | `true` | `false` or `null` |
| `trading_thread_alive` | `true` | `false` or `null` |
| `heartbeat_stale_alerting` | `false` | `true` |
| `restart_exhausted_ingestion` | `false` | `true` |
| `restart_exhausted_trading` | `false` | `true` |
| `restart_attempts_ingestion_last_hour` | `0` | `> 0` (approaching exhaustion) |
| `restart_attempts_trading_last_hour` | `0` | `> 0` (approaching exhaustion) |
| `last_cycle_status` | `"success"` | `"error"` or `null` |
| `last_error_message` | `null` | non-null string (cycle error) |
| `last_component_error` | *(not surfaced in API — internal only)* | — |
| `execution_route_effective` | `"paper"` | `"blocked"` (only in degraded) |
| `trade_mode` | `"paper_auto"` | `"paused"` (if intentionally paused) |
| `uptime_seconds` | `> 0` | `null` if supervisor not running |
| `last_shadow_time` | `null` or ISO timestamp | `null` if no shadows yet |
| `last_restart_time` | `null` (no restart yet) | ISO timestamp of most recent `component_restart_*` event |
| `mode_transition_guard` | `null` | non-null reason string when transition is blocked |

### 2.3 Running the Supervisor

```bash
# Start supervisor (paper-safe loop)
make runtime-supervisor

# Run one-shot cycle (no loop)
make runtime-once

# Tail events live
make runtime-tail-events

# Curl runtime health summary
make runtime-health
```

### 2.3.1 macOS launchd (recommended for long local runs)

```bash
# Install and start LaunchAgent (auto-restart + login auto-start)
make runtime-agent-install

# Status and logs
make runtime-agent-status
make runtime-agent-logs

# Stop and remove
make runtime-agent-stop
make runtime-agent-uninstall
```

Optional custom runtime values:

```bash
INGEST_INTERVAL=120 TRADE_INTERVAL=60 RUNTIME_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT make runtime-agent-install
```

### 2.4 Periodic Inspection Commands

```bash
# Count cycles in last hour (should be ~60 if loop_interval_seconds=60)
curl -s http://localhost:8000/runtime/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Cycles last hour: {d['cycles_last_hour']}\")"

# Check for restart exhaustion
curl -s http://localhost:8000/runtime/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Ingestion exhausted: {d['restart_exhausted_ingestion']}\"); print(f\"Trading exhausted: {d['restart_exhausted_trading']}\")"

# Count orders last hour (paper fills)
curl -s http://localhost:8000/runtime/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Orders last hour: {d['orders_last_hour']}\")"
```

---

## 3. Fault Classification & Response

### 3.1 Severity Levels

| Level | Symbol | Meaning |
|-------|--------|---------|
| **INFO** | `ℹ` | Normal operation, no action needed |
| **DEGRADED** | `⚠` | Partial impairment, monitor closely |
| **NO_NEW** | `🔴` | Cannot open new positions, paper fills may still occur |
| **GLOBAL_PAUSE** | `🛑` | All execution blocked |

### 3.2 DEGRADED (`heartbeat_stale_alerting: true`)

**Symptom**: `heartbeat_stale_alerting: true` in `/runtime/status`

**Cause**: Supervisor heartbeat missed for > 2 minutes.

**Response**:
1. Check if supervisor process is still alive: `ps aux | grep supervisor`
2. If process is dead: restart with `make runtime-supervisor`
3. If process alive but heartbeat missing: check logs for thread crash
4. If `restart_exhausted_ingestion` or `restart_exhausted_trading` is `true`: escalate to NO_NEW

### 3.3 NO_NEW (`restart_exhausted_*` or `execution_route_effective: "blocked"`)

**Symptom**: Either `restart_exhausted_ingestion` or `restart_exhausted_trading` is `true`

**Cause**: A component has attempted the maximum number of restarts in one hour and is now dead.

**Response**:
1. **Do not restart blindly** — investigate root cause first
2. Check `last_component_error` field — note: this field is stored in DB events only; it is **not** exposed via any API endpoint; query it via `python -m trading.runtime.event_tail --event-type supervisor_component_error --limit 5`
3. Review recent events: `make runtime-tail-events`
4. Fix underlying issue (e.g., database lock, API outage, code bug)
5. Restart supervisor only after root cause is understood

**DO NOT** unlock `live_small_auto` mode to "fix" this.

### 3.4 GLOBAL_PAUSE (`execution_route_effective: "blocked"` and `trade_mode: "paused"`)

**Symptom**: `execution_route_effective` is `"blocked"` in `/runtime/status` and `trade_mode` is `paused` or `live_small_auto`.

**Response**:
1. Check `mode_transition_guard` in `/runtime/status` for block reason
2. If `trade_mode` is `paused`: investigate what paused it
3. If `trade_mode` is `live_small_auto`: **this should never happen in paper-safe** — verify `live_trading_enabled: false` and `require_manual_unlock: true` in config
4. Resolve root cause before resuming

### 3.5 Reconciliation (`reconciliation.status` in `/runtime/status`)

**Symptom**: `reconciliation.status` is not `"ok"` in the runtime status response.

Reconciliation runs automatically on every `/runtime/status` call and writes a `reconciliation_ok` or `reconciliation_mismatch` event to the database.

#### Reconciliation Status Values

| Status | Severity | Meaning |
|--------|----------|---------|
| `ok` | info | Balances and positions match within tolerance |
| `balance_mismatch` | warning | Cash balance differs beyond tolerance (default: 1.0 USDT) |
| `position_mismatch` | warning | One or more position quantities differ beyond tolerance |
| `global_pause_recommended` | error | Critical threshold exceeded — full pause recommended |
| `unavailable` | — | Reconciliation could not run (e.g., DB unavailable) |

#### Response

1. **Check the diff summary**: Look at `reconciliation.diff_summary` in `/runtime/status` for the detailed diff (e.g. `balance_diff=2.5 USDT, position_diffs=0, global_pause=false`).

2. **Balance mismatch**: Investigate why local tracked balance diverges from the exchange interface:
   - Paper fills may have rounding differences
   - Fees may not match the exchange-reported fee schedule
   - Check `GET /events/recent?event_type=reconciliation_mismatch` for the latest mismatch event

3. **Position mismatch**: Check which symbol positions differ:
   - Query fills: `GET /orders/recent` and reconstruct positions
   - Verify no fills were lost during a restart

4. **global_pause_recommended**: This triggers only when:
   - `balance_diff > 10.0 USDT` (critical threshold), OR
   - `position_diff_count >= 3` (3+ positions differ simultaneously)

   **Response for global_pause_recommended**:
   ```bash
   # Pause paper trading immediately
   curl -X POST http://localhost:8000/runtime/control-plane/mode \
     -H "Content-Type: application/json" \
     -d '{"to_mode": "paused", "reason": "Reconciliation global pause"}'
   ```
   Then investigate root cause before resuming.

#### Viewing Reconciliation Events

```bash
# View latest reconciliation events
curl -s "http://localhost:8000/events/recent?event_type=reconciliation_ok&limit=5"
curl -s "http://localhost:8000/events/recent?event_type=reconciliation_mismatch&limit=5"

# Or via event_tail CLI
python -m trading.runtime.event_tail --event-type reconciliation_ok --limit 5
python -m trading.runtime.event_tail --event-type reconciliation_mismatch --limit 5
```

#### Reconciliation Thresholds (Read-Only)

| Threshold | Default | Description |
|-----------|---------|-------------|
| `balance_diff_usdt` | 1.0 USDT | Balance diff triggers `balance_mismatch` |
| `balance_critical_usdt` | 10.0 USDT | Balance diff triggers `global_pause_recommended` |
| `position_diff_absolute` | 0.0001 | Position quantity diff triggers mismatch |
| `position_critical_count` | 3 | Number of position diffs to trigger global pause |

These thresholds are defined in `trading/runtime/reconciliation.py` and are not yet runtime-configurable. They are displayed read-only in **Settings > 对账（纸面安全）**.

---

## 4. Recovery Procedure

### 4.1 General Recovery Order

```
1. LOCK  — engage live trading lock first (prevent live route)
2. DIAGNOSE — understand root cause via logs, events, status
3. FIX   — apply fix or rollback
4. VERIFY — confirm /runtime/status shows healthy
5. UNLOCK — only if transitioning to live_shadow or live_small_auto (requires explicit approval)
```

### 4.2 Engaging the Lock (Emergency)

To prevent any live routing in an emergency:

```bash
curl -X POST http://localhost:8000/runtime/control-plane/live-lock \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "reason": "Emergency lock from runbook"}'
```

This sets `live_trading_lock_enabled: true` which blocks `live_shadow` and `live_small_auto` routes. `paper_auto` mode remains unaffected.

### 4.3 Restarting After a Fault

```bash
# Stop current supervisor (Ctrl+C or kill)
# Fix root cause
# Verify config integrity:
bash scripts/release_gate_paper.sh
# Only proceed if gate passes:
make runtime-supervisor
```

If using launchd instead of foreground runtime:

```bash
make runtime-agent-restart
make runtime-agent-status
```

### 4.4 Recovering from Restart Exhaustion

1. Identify which component exhausted: `restart_exhausted_ingestion` or `restart_exhausted_trading`
2. Check `last_component_error` for the error message
3. Check `last_restart_time` to understand when it last tried
4. Common causes:
   - **ingestion exhaustion**: Binance API unreachable for extended period, DB lock contention
   - **trading exhaustion**: repeated risk rejections, AI API failures, order fill issues
5. After fixing: restart supervisor, monitor for 5 minutes

### 4.5 Clearing a Stale Heartbeat Alert

```bash
# Force a new heartbeat by restarting the supervisor
# The heartbeat_stale_alerting will clear when the next supervisor_heartbeat event is recorded
```

---

## 5. Forbidden Operations

> **These operations are banned in paper-safe by design and by operational policy.**

| Forbidden Operation | Why | Alternative |
|--------------------|-----|------------|
| Enable `live_small_auto` mode | Real capital at risk — blocked by default | Use `paper_auto` or `live_shadow` |
| Set `live_trading_enabled: true` in any config file | Enables real exchange access | Stay at `false` |
| Use real Binance API keys | Real orders may be submitted | Use paper-only keys or no keys |
| Unlock `LiveTradingLock` in production | Removes hard safety net | Keep `lock_enabled: false` for paper |
| Bypass `ExecutionGate` | Removes mode enforcement | Route all through the gate |
| Disable `RiskEngine` | No pre-trade checks | Keep RiskEngine enabled |
| Run `live_small_auto` without explicit `allow_live_unlock` | Blocked by transition guard | Requires two-flag explicit unlock |
| Modify `TRADE_MODES` in `gate.py` without review | Changes mode safety semantics | Require code review |
| Skip `release_gate_paper.sh` before deploy | Risk of misconfiguration | Gate is mandatory |

---

## 6. Rollback & Safe Shutdown

### 6.1 Safe Shutdown (Planned)

1. **Stop accepting new cycles** — set mode to `paused`:

```bash
curl -X POST http://localhost:8000/runtime/control-plane/mode \
  -H "Content-Type: application/json" \
  -d '{"to_mode": "paused", "reason": "Planned shutdown"}'
```

2. **Wait for current cycle to finish** — monitor `/runtime/status` for `last_cycle_status: "success"` or cycle count to stop increasing.

3. **Stop the supervisor process** — `Ctrl+C` or `kill $(pgrep -f supervisor)`.

4. **Verify no open orders remain** — check `/orders` or database.

5. **Backup the database**:

```bash
cp data/crypto_ai_trader.sqlite3 "data/backups/$(date +%Y%m%d_%H%M%S)_backup.sqlite3"
```

### 6.2 Emergency Shutdown (Unplanned Fault)

1. **Engage the live trading lock immediately**:

```bash
curl -X POST http://localhost:8000/runtime/control-plane/live-lock \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "reason": "Emergency shutdown"}'
```

2. **Kill the supervisor process** — `kill -9 $(pgrep -f supervisor)` (use `-9` only if graceful stop fails).

3. **Review events for what went wrong** via `make runtime-tail-events` or direct DB query.

4. **Do not restart until root cause is identified**.

### 6.3 Configuration Rollback

To revert a bad config change:

```bash
# Show what changed
git diff config/app.yaml

# Revert
git checkout config/app.yaml
git checkout config/exchanges.yaml

# Re-run gate
bash scripts/release_gate_paper.sh
```

### 6.4 Code Rollback

```bash
# Show recent commits
git log --oneline -10

# Revert to last known good
git revert HEAD   # for last commit
# or
git checkout <good-commit-hash> -- trading/ config/

# Re-run gate
bash scripts/release_gate_paper.sh
```

---

## Appendix: Minimal Executable Inspection Commands

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader

# 1. Ruff lint (must pass)
.venv/bin/ruff check .

# 2. Pytest (must pass)
.venv/bin/pytest -q

# 3. Dashboard build (must pass)
cd dashboard && npm run build && cd ..

# 4. DB initialisation check
.venv/bin/python -c "from trading.storage.db import create_database_engine, init_db; from trading.runtime.config import AppSettings; engine = create_database_engine(AppSettings().database_url); init_db(engine); print('OK')"

# 5. Runtime status (backend must be running)
curl -s http://localhost:8000/runtime/status | .venv/bin/python -m json.tool

# 6. Control plane snapshot
curl -s http://localhost:8000/runtime/control-plane | .venv/bin/python -m json.tool

# 7. Recent events (last 30)
.venv/bin/python -m trading.runtime.event_tail --limit 30

# 8. Risk status (requires day_start_equity and current_equity query params)
curl -s "http://localhost:8000/risk/status?day_start_equity=500&current_equity=500" | .venv/bin/python -m json.tool

# 9. Release gate (full paper-safe check)
bash scripts/release_gate_paper.sh
```

---

## Appendix: API Reference Summary

### `GET /runtime/status`

```
trade_mode                            string  — current mode: paper_auto / paused / live_shadow / live_small_auto
live_trading_lock_enabled             bool    — live lock state
execution_route_effective             string  — paper / shadow / blocked
supervisor_alive                      bool|null
ingestion_thread_alive                bool|null
trading_thread_alive                 bool|null
uptime_seconds                        int|null
last_heartbeat_time                   string|null  ISO timestamp
heartbeat_stale_alerting              bool        — True when heartbeat is lost and not yet recovered
last_recovered_time                   string|null  ISO timestamp; most recent heartbeat_recovered event
restart_attempts_ingestion_last_hour  int
restart_attempts_trading_last_hour    int
restart_exhausted_ingestion           bool
restart_exhausted_trading             bool
last_restart_time                     string|null  ISO timestamp of most recent component restart event
last_cycle_status                     string|null
last_cycle_time                      datetime|null
last_error_message                    string|null
cycles_last_hour                     int
orders_last_hour                     int
shadow_executions_last_hour          int
last_shadow_time                     string|null  ISO timestamp
mode_transition_guard                string|null  reason string from validate_mode_transition
reconciliation.status                string       ok / balance_mismatch / position_mismatch / global_pause_recommended / unavailable
reconciliation.last_check_time       string|null  ISO timestamp of last reconciliation run
reconciliation.diff_summary          string       human-readable diff summary

Note: `last_component_error` is stored in DB events only; it is not exposed in any API endpoint. Query it via:
```
python -m trading.runtime.event_tail --event-type supervisor_component_error --limit 5
```

### `GET /runtime/control-plane`

```
trade_mode                            string
lock_enabled                         bool
lock_reason                          string|null
execution_route                     string  (paper / shadow / blocked)
transition_guard_to_live_small_auto  string
```

### `POST /runtime/control-plane/mode`

Request: `{"to_mode": "paper_auto", "allow_live_unlock": false, "reason": "optional string"}`

Response: `{"success": bool, "current_mode": string, "guard_reason": string}`

Note: `allow_live_unlock` is required and must be `true` to transition to `live_small_auto`.

### `POST /runtime/control-plane/live-lock`

Request: `{"enabled": true, "reason": "optional string"}`

Response: `{"success": bool, "lock_enabled": bool, "reason": string}`

### `GET /risk/status`

Query params: `day_start_equity` (default 500), `current_equity` (default 500)

Response: full risk state with profile, thresholds, and risk_state enum.
