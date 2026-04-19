# Claude Code Repair Task: Dashboard Partial API Failure Visibility

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

This is a small repair task for commit `a41c261 fix: repair dashboard local connectivity`. Keep the patch focused. Do not start a new feature.

## Problem To Fix

The previous repair added a useful offline placeholder state, but `dashboard/src/App.tsx` only sets `offline` when every API response is missing:

```ts
const offline = !health && !risk && !portfolio && !orders && !events;
```

That means if `/health` succeeds but `/risk/status`, `/portfolio/status`, `/orders/recent`, or `/events/recent` fails, the Dashboard does not show the offline/degraded notice and does not use placeholders for the failed panels. This violates the task requirement:

> Keep the offline notice visible when any primary API call fails.

## Required Behavior

Update the Dashboard so it tracks API call failures explicitly.

Requirements:

- Show an offline/degraded notice if any primary API call fails.
- Keep using real data for API calls that succeed.
- Use placeholder/fallback data only for panels whose API call failed or has no data.
- Required fallback values remain:
  - mode: `paper_auto`
  - live trading: disabled
  - risk state: normal
  - profile: small_balanced
  - account equity: 500
  - cash balance: 500
  - today PnL: 0
  - max trade risk: 7.5
- If `/events/recent` fails, show the placeholder backend-offline event.
- Do not show fake orders or fake open positions.
- Avoid hiding successful data just because another endpoint failed.

Implementation suggestion:

- Add a small failure state object, for example:

```ts
const [failures, setFailures] = useState({
  health: false,
  risk: false,
  portfolio: false,
  orders: false,
  events: false,
});
```

- Set the corresponding key to `true` in each `.catch`.
- Derive `hasApiFailure = Object.values(failures).some(Boolean)`.
- Use per-panel fallback booleans such as `riskFailed`, `portfolioFailed`, and `eventsFailed`.

## Files To Edit

- `dashboard/src/App.tsx`
- `docs/claude-tasks/last-result.md`

Only edit CSS if necessary. Do not touch backend code unless you find a direct need.

## Safety Rules

Do not implement:

- Order execution
- Live trading
- Binance private endpoints
- API key handling
- Secret storage
- Any POST/PUT/PATCH/DELETE trading control endpoint
- Any bypass of RiskEngine/ExecutionGate/LiveTradingLock

This repair must remain frontend visibility only.

## Verification

Run:

```bash
cd dashboard
npm run build
cd ..
.venv/bin/ruff check .
.venv/bin/pytest -q
git status --short
```

The final `git status --short` should be clean except expected files staged/committed, and it must not show `.omc/`, `dashboard/dist`, or `dashboard/node_modules`.

## Commit

If verification passes:

```bash
git add dashboard/src/App.tsx docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "fix: show dashboard partial API failures"
```

Do not commit unrelated files.

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Dashboard Partial API Failure Visibility
Status: completed | failed

Files changed:
- ...

Verification:
- ...

Commit:
- ...

Safety:
- No order execution added.
- No private Binance API added.
- No API key handling added.
- No live trading added.
- Dashboard remains read-only.

Notes:
- ...
```

Then stop. Do not start another task.
