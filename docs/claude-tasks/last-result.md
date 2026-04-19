# Task: E — Align Docs with Paper-Safe Implementation

## Goal

Align README.md, docs/runbook-paper-ops.md, and dashboard/README.md with current code implementation (fields/paths/commands must be consistent).

## Status

✅ Complete

## Changes

### 1. README.md

- **`make runtime-loop` → `make runtime-supervisor`**: The Makefile defines `runtime-supervisor` (with `--supervisor` flag) as the long-running loop target. `runtime-loop` does not exist. Fixed all references (3 occurrences) to use `runtime-supervisor`.
- **Health check table**: Removed `last_component_error` (not in `/runtime/status` API) and `risk_state` (belongs to `/risk/status`, not `/runtime/status`). Replaced with correct `/runtime/status` fields: `heartbeat_stale_alerting`, `restart_exhausted_ingestion`, `restart_exhausted_trading`.
- **Symptom table**: Replaced `risk_state: no_new_positions/global_pause/emergency_stop` with the actual runtime status field `restart_exhausted_ingestion` or `restart_exhausted_trading` is `true`.

### 2. docs/runbook-paper-ops.md

- **DB init command (section 1.3)**: Fixed wrong import `create_engine` → `create_database_engine` (which is the correct wrapper in `trading.storage.db`). Also removed unused `RuntimeControlRepository` import. Command now uses `AppSettings().database_url` for consistency.
- **Section 3.4 (GLOBAL_PAUSE)**: Fixed field reference `execution_route` → `execution_route_effective` to match `/runtime/status` API response field name. Also fixed symptom description to use correct field `mode_transition_guard` from `/runtime/status` (not `/runtime/control-plane`).
- **Appendix API reference**: Removed `last_component_error` from `/runtime/status` field listing (it's not returned by the API). Added note explaining where to find it: `python -m trading.runtime.event_tail --event-type supervisor_component_error --limit 5`.

### 3. dashboard/README.md

- No changes needed — already aligned with current implementation.

## Files Changed

| File | Change |
|------|--------|
| `README.md` | Fixed `make runtime-loop` → `make runtime-supervisor` (3×); fixed health table fields |
| `docs/runbook-paper-ops.md` | Fixed DB init command import; fixed section 3.4 field names; fixed API reference appendix |
| `docs/claude-tasks/last-result.md` | This report |

## Verification

```bash
# 1. Ruff lint
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/ruff check .
# Result: All checks passed!

# 2. Pytest
.venv/bin/pytest -q
# Result: 349 passed in 11.78s

# 3. Dashboard build
cd dashboard && npm run build && cd ..
# Result: ✓ built in 355ms
```

## Residual Risks

1. **API field documentation drift**: As the codebase evolves, `/runtime/status` and `/runtime/control-plane` fields may change. The docs are aligned as of this fix but will drift again without a sync mechanism.
2. **Dashboard README is minimal**: The dashboard README is short and mostly accurate. No changes were needed, but it lacks detail on the control panel features added in previous tasks.
3. **`runtime-loop` Makefile target**: The Makefile only has `runtime-supervisor`, not `runtime-loop`. If a future Makefile change adds `runtime-loop`, the README would need to reflect the distinction.
