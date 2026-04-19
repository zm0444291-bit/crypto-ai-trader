# Claude Code Task: Milestone 6 Dashboard Completion (Read-Only, Paper-Only)

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Upgrade the dashboard from current single-page status view into a complete multi-page control room for paper trading operations:

- Overview
- Signals
- Orders
- Risk
- Analytics
- Extensions
- Logs
- Settings

This milestone is **UI/API visibility only**. No trade execution controls, no live mode actions.

## Read First

- `/Users/zihanma/Desktop/crypto-ai-trader/dashboard/src/App.tsx`
- `/Users/zihanma/Desktop/crypto-ai-trader/dashboard/src/api/client.ts`
- `/Users/zihanma/Desktop/crypto-ai-trader/dashboard/src/styles.css`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/main.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/dashboard_api/routes_*.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/README.md`
- `/Users/zihanma/Desktop/crypto-ai-trader/dashboard/README.md`

## Required Scope

### 1) Frontend routing and page layout

- Add a lightweight page-navigation structure (tab or sidebar) in React.
- Implement pages:
  - `Overview`
  - `Signals`
  - `Orders`
  - `Risk`
  - `Analytics`
  - `Extensions`
  - `Logs`
  - `Settings`
- Keep current dashboard visual constraints:
  - no card-inside-card
  - border radius <= 8px
  - letter-spacing must be 0
  - avoid dominant dark blue/slate single-tone palette

### 2) Data mapping per page (read-only)

- Reuse existing APIs where possible.
- Add only missing **GET** APIs if needed; no POST/PUT/DELETE.

Required page content:

1. Overview
   - Mode / live flag / risk state
   - account metrics
   - runtime heartbeat
   - latest critical events

2. Signals
   - recent signal/cycle-related events
   - candidate present/no-signal/rejected/executed counts (time-window summary)
   - explicit reason fields where available

3. Orders
   - existing recent orders table
   - last-hour and last-24h aggregates

4. Risk
   - profile + thresholds (pct and USDT where available)
   - current risk state + reason
   - recent risk reject events

5. Analytics
   - equity snapshot trend (simple line/list is fine; no heavy chart lib required)
   - win/loss proxy stats derived from fills/orders/events
   - daily pnl summary from available data

6. Extensions
   - render static disabled extension templates from design:
     - FuturesMomentumTemplate
     - OrderBookImbalanceTemplate
     - CrossExchangeArbitrageTemplate
     - NewsSentimentTemplate
     - OnchainFlowTemplate
     - MLSignalTemplate
   - all shown as disabled/read-only with reason + next milestone

7. Logs
   - recent events feed with filtering by severity/component

8. Settings
   - read-only system settings summary
   - explicit “paper mode only” safety notice
   - no editable secrets, no execution toggles

### 3) Degraded/offline behavior

- Preserve and extend current partial-failure behavior:
  - per-endpoint failure tracking
  - failed panels show placeholders
  - successful panels keep real data
- Keep a visible degraded/offline banner when any critical endpoint fails.

### 4) Backend (only if required for missing visibility)

- If adding backend routes, keep them strictly read-only under `trading/dashboard_api/`.
- Wire routers in `trading/main.py`.
- Add integration tests for new endpoints.

## Safety Constraints (strict)

- No live trading implementation.
- No private Binance API usage.
- No API key handling changes.
- No order placement API.
- Do not bypass RiskEngine / execution safety boundaries.

## Tests & Verification (required)

Run:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/ruff check .
.venv/bin/pytest -q
cd /Users/zihanma/Desktop/crypto-ai-trader/dashboard
npm run build
cd /Users/zihanma/Desktop/crypto-ai-trader
git status --short
```

If backend routes were added, include focused integration tests and run them explicitly too.

## Commit

If verification passes:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
git add dashboard/src trading/dashboard_api trading/main.py tests README.md dashboard/README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: complete milestone 6 multi-page read-only dashboard"
```

## Completion Report

Write `/Users/zihanma/Desktop/crypto-ai-trader/docs/claude-tasks/last-result.md` with:

- Task
- Status
- Files changed
- Verification output summary
- Commit hash
- Safety checklist confirmation

Then stop.
