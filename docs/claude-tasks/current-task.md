# Claude Code Task: Milestone 6.1 Local Dashboard Frontend Skeleton

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

Your job is to build the first local Dashboard frontend skeleton. Keep the work small, safe, and reviewable. This is a UI/read-only visibility task only.

## Read First

Read these files before editing:

- `README.md`
- `docs/claude-collaboration.md`
- `docs/superpowers/specs/2026-04-19-crypto-ai-trader-design.md`
- `trading/main.py`
- `trading/dashboard_api/routes_health.py`
- `trading/dashboard_api/routes_market_data.py`
- `trading/dashboard_api/routes_orders.py`
- `trading/dashboard_api/routes_risk.py`
- `trading/dashboard_api/routes_portfolio.py`
- `trading/dashboard_api/routes_events.py`
- Existing tests under `tests/integration/`

## Current Backend APIs Available

The Dashboard should consume these read-only endpoints:

- `GET /health`
- `GET /market-data/status`
- `GET /risk/status?day_start_equity=500&current_equity=500`
- `GET /portfolio/status?initial_cash_usdt=500`
- `GET /orders/recent`
- `GET /events/recent`

Do not add order placement, live trading controls, API key forms, private Binance calls, or any endpoint that can execute a trade.

## Goal

Create a Vite + React + TypeScript local Dashboard app under `dashboard/`.

The first screen should be the actual control room, not a marketing page. It should show a clear local trading operations dashboard using mocked/fallback data when the backend is not running, and real API data when the backend is available.

The UI must prioritize:

- Safety status
- Risk state
- Paper portfolio visibility
- Recent orders
- Recent system/risk events
- Obvious read-only mode

## Files To Create

Create a small frontend app:

- `dashboard/package.json`
- `dashboard/index.html`
- `dashboard/tsconfig.json`
- `dashboard/vite.config.ts`
- `dashboard/src/main.tsx`
- `dashboard/src/App.tsx`
- `dashboard/src/api/client.ts`
- `dashboard/src/styles.css`
- `dashboard/README.md`

You may add a small number of extra component files if it keeps `App.tsx` readable, but avoid over-engineering.

## Required Product Behavior

The Dashboard should render:

1. Top-level title: `Trading Control Room`
2. A clearly visible status strip showing:
   - trade mode
   - live trading enabled/disabled
   - risk state
   - risk profile
3. Main metrics:
   - account equity
   - cash balance
   - today PnL percent
   - max trade risk USDT
4. Positions section:
   - symbol
   - qty
   - average entry
   - market value
   - unrealized PnL
5. Recent orders section:
   - symbol
   - side
   - status
   - requested notional
   - created time
6. Recent events section:
   - severity
   - component
   - event type
   - message
   - created time
7. Safety banner that says this build is read-only and paper-mode oriented.

When API calls fail, show a calm fallback state instead of a blank screen. The fallback must make it obvious that data is placeholder/offline.

## Visual Direction

Make it beautiful but restrained:

- No landing page.
- No card-inside-card layouts.
- No purple/purple-blue dominant gradients.
- No beige/cream/sand/tan, brown/orange/espresso, or dark blue/slate dominant theme.
- Use a crisp professional quant terminal/control-room feeling with a balanced palette.
- Use only modest radius: 8px or less.
- Text must not overflow on mobile.
- Layout must work on desktop and mobile.
- Do not use decorative orbs/blob backgrounds.
- Use clear data hierarchy and strong spacing.

Because this is a dashboard/tool, images are not required. Do not fetch remote assets.

## API Client Requirements

In `dashboard/src/api/client.ts`:

- Use `fetch`.
- Base URL should default to `http://127.0.0.1:8000`.
- Allow override with `VITE_API_BASE_URL`.
- Provide typed functions:
  - `getHealth()`
  - `getMarketDataStatus()`
  - `getRiskStatus()`
  - `getPortfolioStatus()`
  - `getRecentOrders()`
  - `getRecentEvents()`
- Keep types local and simple.
- Fail gracefully by throwing useful errors for the caller to catch.

## Safety Rules

Do not implement:

- Order execution
- Live trading
- Binance private endpoints
- API key handling
- Secret storage
- Kill-switch behavior that changes backend state
- Any POST/PUT/PATCH/DELETE trading control endpoint
- Any bypass of RiskEngine/ExecutionGate/LiveTradingLock

This task is frontend visibility only.

## Testing / Verification

Prefer lightweight verification that works in a fresh local project.

At minimum:

```bash
cd dashboard
npm install
npm run build
```

Then from project root:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
git status --short
```

If Node/npm is not available, do not fake success. Record the blocker in `docs/claude-tasks/last-result.md`.

## Commit

If verification passes, commit only the relevant files:

```bash
git add dashboard docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add local dashboard skeleton"
```

Do not commit unrelated local files.

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Milestone 6.1 Local Dashboard Frontend Skeleton
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
