# Task: Dashboard Control Plane Interactions

## Goal

Add a "Security Control Panel" to the Dashboard Settings page for initiating mode switches and live-lock toggling with result/error feedback.

## Status

✅ Complete

## Changes

### 1. API Client (`dashboard/src/api/client.ts`)

- Added TypeScript types: `TradeMode`, `ModeChangeRequest`, `ModeChangeResponse`, `LiveLockChangeRequest`, `LiveLockChangeResponse`
- Added `setControlPlaneMode(mode, allowLiveUnlock, reason?)` — POST `/runtime/control-plane/mode`
- Added `setLiveLock(enabled, reason?)` — POST `/runtime/control-plane/live-lock`
- Both throw on failure with the backend `reason`/`detail` message

### 2. Settings Page (`dashboard/src/pages/Settings.tsx`)

New "Execution Control Actions" section with:

**Mode control block:**
- `<select>` for `mode` (paused / paper_auto / live_shadow / live_small_auto)
- Checkbox for `allow_live_unlock`
- Text input for optional `reason`
- "Apply Mode" button with loading state
- Feedback banner (green ✓ / red ✗) after response

**Live Lock control block:**
- Checkbox for `enabled`
- Text input for optional `reason`
- "Apply Lock" button with loading state
- Feedback banner after response

**State refresh:** After a successful operation, fetches fresh `/runtime/status` and `/runtime/control-plane`

**Guard warning:** When `transition_guard_to_live_small_auto` starts with `blocked:`, displays a prominent warning banner above the form

### 3. Backend Endpoints (`trading/dashboard_api/routes_runtime.py`)

- `POST /runtime/control-plane/mode` — validates transition, persists mode, returns `ModeChangeResponse`
- `POST /runtime/control-plane/live-lock` — persists lock state, returns `LiveLockChangeResponse`
- Both are fail-closed (any exception returns error response without state change)
- No live trading is triggered by these endpoints

### 4. Styles (`dashboard/src/styles.css`)

Added minimal styles for new UI elements:
- `.guard-warning-banner` — red alert banner for active transition guard
- `.feedback-banner` / `.feedback-success` / `.feedback-error` — result feedback
- `.control-action-group` / `.control-action-label` / `.control-action-row`
- `.control-input` — text input styling
- `.control-btn` — action button with hover/disabled states
- `.toggle-label` — checkbox label with accent color

## Files Changed

| File | Change |
|------|--------|
| `dashboard/src/api/client.ts` | Added `setControlPlaneMode`, `setLiveLock`, new types |
| `dashboard/src/pages/Settings.tsx` | Added control panel UI with mode/lock actions |
| `dashboard/src/styles.css` | Added control panel, feedback, guard warning styles |
| `trading/dashboard_api/routes_runtime.py` | Added `POST /mode` and `POST /live-lock` endpoints |

## Verification

```bash
# Backend lint
.venv/bin/ruff check .           # All checks passed

# Frontend build
cd dashboard && npm run build     # ✓ built in 357ms
```

## Commit

```bash
git add dashboard/src/api/client.ts dashboard/src/pages/Settings.tsx \
       dashboard/src/styles.css trading/dashboard_api/routes_runtime.py \
       docs/claude-tasks/last-result.md
git commit -m "feat: add dashboard control panel for mode and live-lock changes"
```

## Safety Checklist

- [x] No live trading — endpoints only change mode/lock state, ExecutionGate remains
- [x] No private Binance API — no key handling changes
- [x] No write endpoints for order placement
- [x] No bypass of risk/kill-switch/ExecutionGate
- [x] Fail-closed: any exception returns error without state mutation
- [x] Error messages from backend shown to user, not swallowed
- [x] Loading states during async operations
- [x] Guard warning banner shown when transition is blocked
