# Task: Shadow Execution Recording Pipeline for live_shadow Mode

## Goal

Implement a paper-safe shadow execution recording pipeline for `live_shadow` mode that records hypothetical execution plans/results only. Must NOT place real orders.

## Status

✅ Complete

## Changes

### 1. Data Model (`trading/storage/models.py`)

- Added `ShadowExecution` ORM model with fields:
  - `id` (primary key)
  - `symbol`
  - `side`
  - `planned_notional_usdt`
  - `reference_price`
  - `simulated_fill_price`
  - `simulated_slippage_bps`
  - `decision_reason`
  - `source_cycle_status` (optional)
  - `created_at` (indexed)
- Table `shadow_executions` auto-created via `Base.metadata.create_all()`

### 2. Repository Support (`trading/storage/repositories.py`)

- Added `ShadowExecutionRepository` class with methods:
  - `record_shadow_execution(...)` — persists a shadow record and returns it
  - `list_recent_shadow(limit=50)` — returns newest-first list
  - `count_last_hour(cutoff)` — counts records created after cutoff datetime

### 3. Execution Gate Integration (`trading/runtime/paper_cycle.py`)

- When gate route is `shadow` (live_shadow mode):
  - Does NOT call `PaperExecutor.execute_market_buy` — no real order
  - Computes simulated fill price using same slippage formula as PaperExecutor
  - Creates and persists shadow execution record via `ShadowExecutionRepository`
  - Emits `shadow_execution_recorded` event
  - Finishes cycle with status `shadow_recorded`
- `paper_auto` route behavior unchanged — still executes paper orders
- `blocked` routes remain blocked

### 4. Runtime Status Visibility (`trading/dashboard_api/routes_runtime.py`)

- Extended `RuntimeStatusResponse` with:
  - `shadow_executions_last_hour: int` — count of shadow records in last hour
  - `last_shadow_time: str | None` — ISO timestamp of most recent shadow record
- Safe defaults (0 / null) when DB unavailable or no data
- Both fields appear in all three return paths (early-exception, success, late-exception)

### 5. Dashboard Visibility (`dashboard/src/pages/Overview.tsx`, `dashboard/src/api/client.ts`)

- `RuntimeStatus` TypeScript interface extended with new fields
- `PLACEHOLDER_RUNTIME` updated with safe defaults
- Added two new metric cards in Runtime section:
  - **Shadow / Hour** — shows `shadow_executions_last_hour`
  - **Last Shadow** — shows formatted `last_shadow_time` or `—`

## Files Changed

| File | Change |
|------|--------|
| `trading/storage/models.py` | Added `ShadowExecution` model |
| `trading/storage/repositories.py` | Added `ShadowExecutionRepository` |
| `trading/runtime/paper_cycle.py` | Added shadow route handling in cycle |
| `trading/dashboard_api/routes_runtime.py` | Added shadow fields to RuntimeStatusResponse |
| `dashboard/src/api/client.ts` | Added shadow fields to RuntimeStatus interface |
| `dashboard/src/pages/Overview.tsx` | Added Shadow/Hour and Last Shadow metric cards |
| `tests/unit/test_shadow_execution_repository.py` | New file — repository unit tests |
| `tests/unit/test_paper_cycle.py` | Added shadow route tests + paper_auto regression test |
| `tests/integration/test_runtime_status_api.py` | Added shadow field tests + empty-db shadow assertions |

## Verification

```bash
# Backend lint
.venv/bin/ruff check .
# All checks passed

# Backend tests
.venv/bin/pytest -q
# 288 passed in 2.40s

# Frontend build
cd dashboard && npm run build
# ✓ built in 361ms

# Git status
git status --short
#  M tests/unit/test_paper_cycle.py
#  M tests/integration/test_runtime_status_api.py
# (implementation files already in HEAD from prior work)
```

## Commit

```bash
git add tests/unit/test_paper_cycle.py tests/integration/test_runtime_status_api.py
git commit -m "feat: add shadow execution recording pipeline for live_shadow mode"
```

## Safety Checklist

- [x] No real order placement — shadow mode only records hypotheticals
- [x] No private Binance API integration
- [x] No live exchange client wiring
- [x] No API keys for trading used or added
- [x] No bypass of risk/kill-switch/gate — all safety checks remain intact
- [x] paper_auto mode behavior unchanged — still executes paper orders
- [x] blocked routes remain blocked
- [x] All new fields have safe defaults (0 / null)
- [x] Dashboard is read-only — no trading controls added
