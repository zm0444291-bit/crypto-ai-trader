# Claude Code Repair Task: Fix Review Findings (Dependency + Recovery + Docs)

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

Fix all review findings below in one focused patch.

## Findings To Fix

1. `pyproject.toml` is missing runtime dependency for Telegram notifier:
   - `trading/notifications/telegram_notifier.py` imports `requests`
   - add `requests` to `[project].dependencies` in `pyproject.toml`
   - do **not** remove existing dependencies

2. Dashboard failure flags never recover:
   - in `dashboard/src/App.tsx`, each API success must clear its corresponding `failures.<panel>` flag back to `false`
   - keep existing per-panel fallback behavior
   - keep offline notice behavior (`hasApiFailure`) based on current failure state, not stale state

3. README quickstart has wrong API paths and DB filename:
   - in `README.md`, fix health/runtime URLs:
     - `/api/health` -> `/health`
     - `/api/runtime/status` -> `/runtime/status`
   - fix DB filename reference:
     - `data/crypto_trader.db` -> `data/crypto_ai_trader.sqlite3`
   - keep all content paper-only, no live trading instructions

4. Dashboard README CORS guidance contradicts backend:
   - in `dashboard/README.md`, align CORS section with backend allowlist:
     - both `http://127.0.0.1:5173` and `http://localhost:5173` are allowed
   - keep troubleshooting practical and concise

## Safety Rules

- No order execution changes
- No live trading changes
- No Binance private API
- No API key handling changes
- No bypass of RiskEngine/ExecutionGate/LiveTradingLock

## Verification (required)

Run:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader/dashboard && npm run build
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/ruff check .
.venv/bin/pytest -q
git status --short
```

## Commit

If verification passes:

```bash
git add pyproject.toml dashboard/src/App.tsx README.md dashboard/README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "fix: address dependency recovery and docs review findings"
```

## Completion Report

Write `docs/claude-tasks/last-result.md` in this format:

```text
# Last Claude Code Result

Task: Fix review findings (dependency + recovery + docs)
Status: completed | failed

Files changed:
- ...

Verification:
- ...

Commit:
- ...

Safety:
- No order execution changes.
- No live trading changes.
- No private Binance API changes.
- No API key handling changes.

Notes:
- ...
```

Then stop.

