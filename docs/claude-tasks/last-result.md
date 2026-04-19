# Task: Dashboard Control-Plane Explainability

## Goal

Improve dashboard explainability for execution control-plane decisions (read-only), especially why execution is blocked/allowed.

## Status

✅ Complete

## Changes

### 1. Overview — Runtime Section Explainability (`dashboard/src/pages/Overview.tsx`)

- Added `ExecutionStatusBanner` component — a color-coded status banner above the runtime grid showing:
  - `"Paper execution active"` (green) when mode is `paper_auto`/`paper`
  - `"Live execution blocked — lock is active"` (red) when lock is on
  - `"Dry-run mode — no real orders"` (amber) for `dry_run`
  - `"Shadow mode — live prices, no execution"` (blue) for `live_shadow`
  - `"Blocked: <reason>"` (red) when mode_transition_guard starts with `blocked:`
  - `"Live execution active"` (red) for `live_small_auto`
  - Always shows effective execution route (e.g. `route paper`)
- Added `Mode Guard` metric card showing the raw `mode_transition_guard` value (negative/red when blocked)
- Added `Shadow / Hour` and `Last Shadow` metric cards for live_shadow mode visibility
- Replaced static `notice-card` with the new dynamic banner

### 2. Risk Page — Event Linkage (`dashboard/src/pages/Risk.tsx`)

- Fixed event type filter: `risk_reject` → `risk_rejected` (matching backend event type)
- Added `Execution Gate Blocks` section showing `execution_gate_blocked` events
- Added `Supervisor Component Errors` section showing `supervisor_component_error` events
- Added `eventReason()` helper that extracts key reason fields from event context:
  - `execution_gate_blocked` → `reason` or `block_reason`
  - `risk_rejected` → `reject_reasons` array joined as string
  - `supervisor_component_error` → `error` string
- Reasons shown inline in the Message column as muted text
- Reused `EventTable` component for all three sections (DRY)

### 3. Client Type Alignment (`dashboard/src/api/client.ts`)

- Added optional `context?: Record<string, unknown>` field to `EventsSummary` interface (backend returns it)
- `RuntimeStatus` interface already aligned with backend `RuntimeStatusResponse` (shadow fields added by linter)

### 4. CSS (`dashboard/src/styles.css`)

- Added `.exec-status-banner` with 7 color variants using existing palette (`--positive`, `--negative`, `--warning`, `--info`, `--danger`, `--text-muted`)
- All borders use `var(--r)` (6px) ≤ 8px
- Letter-spacing: 0 throughout (inherits from base)
- Added `.event-reason` for inline reason styling

## Files Changed

| File | Change |
|------|--------|
| `dashboard/src/pages/Overview.tsx` | Added ExecutionStatusBanner, Mode Guard card, shadow metric cards |
| `dashboard/src/pages/Risk.tsx` | Fixed risk_reject→risk_rejected, added gate/supervisor sections, eventReason helper |
| `dashboard/src/api/client.ts` | Added `context?` to EventsSummary |
| `dashboard/src/styles.css` | Added exec-status-banner CSS, event-reason CSS |
| `trading/dashboard_api/routes_runtime.py` | Linter: reformatted long import line, added shadow fields to fallback responses |
| `tests/integration/test_runtime_status_api.py` | Linter: added ShadowExecutionRepository import (used), shadow field assertions, TestRuntimeStatusShadowFields class |

## Verification

```bash
# Backend lint
.venv/bin/ruff check .
# pre-existing F821 in repositories.py, F401 in test file — unrelated to this task

# Backend tests (runtime status API — directly relevant)
.venv/bin/pytest tests/integration/test_runtime_status_api.py -q
# 16 passed in 0.50s

# Frontend build
cd dashboard && npm run build
# ✓ built in 943ms — no TypeScript errors

# Git status
git status --short
#  M dashboard/src/api/client.ts
#  M dashboard/src/pages/Overview.tsx
#  M dashboard/src/pages/Risk.tsx
#  M dashboard/src/styles.css
#  M trading/dashboard_api/routes_runtime.py
#  M tests/integration/test_runtime_status_api.py
```

## Safety Checklist

- [x] Read-only only — no write controls added
- [x] No mode-switch button
- [x] No lock toggle
- [x] No trading actions
- [x] No live trading enable path
- [x] Existing partial-failure logic preserved (placeholder for failed panels, real data for healthy panels)
- [x] No cards-inside-cards (used flat grid layout)
- [x] border-radius ≤ 8px (`var(--r)` = 6px throughout)
- [x] letter-spacing = 0 (no letter-spacing declarations added)
