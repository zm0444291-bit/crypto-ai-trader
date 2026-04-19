# Claude Code Repair Task: Dashboard Local Connectivity And UI Compliance

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

This is a repair task for commit `8c04866 feat: add local dashboard skeleton`. Keep the patch small and focused. Do not start a new feature.

## Problems To Fix

1. The Vite dashboard runs from `http://127.0.0.1:5173`, but the FastAPI backend runs from `http://127.0.0.1:8000`. The frontend uses absolute `fetch("http://127.0.0.1:8000/...")`, and `trading/main.py` does not configure CORS. In a real browser, the Dashboard will fail to read backend APIs even though `npm run build` passes.
2. The Dashboard claims fallback/placeholder behavior, but when the backend is unavailable it mostly renders dashes and empty tables, not meaningful placeholder operational data.
3. The Dashboard styling violates the visual constraints from the task: the current palette is dominated by dark blue/slate colors, and CSS uses nonzero `letter-spacing`.
4. `.omc/` is currently untracked after the Claude Code run. It should be ignored so future reviews start from a clean worktree.

## Read First

- `docs/claude-tasks/current-task.md`
- `docs/claude-tasks/last-result.md`
- `trading/main.py`
- `tests/integration/test_app_smoke.py`
- `dashboard/src/App.tsx`
- `dashboard/src/api/client.ts`
- `dashboard/src/styles.css`
- `.gitignore`

## Required Fixes

### 1. Add Local CORS Support

In `trading/main.py`, configure FastAPI with `CORSMiddleware`.

Allow only local dashboard development origins:

- `http://127.0.0.1:5173`
- `http://localhost:5173`

Do not use wildcard `"*"` origins.

Add or update integration tests to prove CORS behavior:

- An OPTIONS preflight request from `http://127.0.0.1:5173` to `/health` returns the expected CORS allow-origin header.
- A request from an unapproved origin does not receive that allow-origin header.

### 2. Add Real Offline Placeholder Data

When the backend is unavailable, the Dashboard should still render a useful offline preview with explicit placeholder values, not only dashes.

Requirements:

- Keep the offline notice visible when any primary API call fails.
- Show placeholder/fallback values for:
  - mode: `paper_auto`
  - live trading: disabled
  - risk state: normal
  - profile: small_balanced
  - account equity: 500
  - cash balance: 500
  - today PnL: 0
  - max trade risk: 7.5
- Show at least one placeholder event stating that the backend is offline and placeholder data is being displayed.
- Do not show fake orders or fake open positions unless they are clearly marked as placeholder. Prefer no fake positions and no fake orders.

### 3. Make CSS Comply With Visual Constraints

Update `dashboard/src/styles.css`:

- Avoid a dominant dark blue/slate theme. Use a neutral dark graphite/black base with balanced green/cyan/red accents.
- Set all `letter-spacing` values to `0`.
- Keep border radius at `8px` or less.
- Keep the dashboard readable on mobile.

### 4. Ignore Claude Local State

Update `.gitignore` to include:

```gitignore
.omc/
```

Do not commit `.omc/`.

## Safety Rules

Do not implement:

- Order execution
- Live trading
- Binance private endpoints
- API key handling
- Secret storage
- Any POST/PUT/PATCH/DELETE trading control endpoint
- Any bypass of RiskEngine/ExecutionGate/LiveTradingLock

This repair must remain dashboard visibility and local connectivity only.

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

The final `git status --short` should not show `.omc/`.

## Commit

If verification passes:

```bash
git add .gitignore trading/main.py tests dashboard docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "fix: repair dashboard local connectivity"
```

Do not commit `dashboard/dist`, `dashboard/node_modules`, `.omc/`, or unrelated files.

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Dashboard Local Connectivity And UI Compliance Repair
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
