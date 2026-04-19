# Claude Code Repair Task: Fix Daily Risk Baseline + Freshness Timezone + CORS Docs

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

Fix all 3 review findings in one focused patch.

## Findings To Fix

### 1) P1: `day_start_equity` resets each cycle (risk gate weakened)

File: `trading/runtime/runner.py`

Current bug:
- `_build_cycle_inputs` sets `day_start_equity = account_equity` every cycle.
- This collapses daily loss toward zero and prevents proper `degraded/no_new/global_pause` transitions.

Required fix:
- Persist and reuse a daily opening equity baseline.
- Baseline behavior:
  - On first cycle of a UTC day, create/open baseline for that day.
  - Reuse same baseline for all cycles in that day.
  - On next UTC day, create a new baseline.
- Keep implementation simple and local-first:
  - You may store baseline in runtime events (`event_type` like `day_start_equity_set`) and read it back.
  - Or add a minimal storage table/model if cleaner, but keep scope small.
- Ensure `CycleInput.day_start_equity` uses this persisted baseline, not current equity.

Add tests:
- update/add tests in `tests/unit/test_runtime_runner.py` (or a focused new test file)
- cover:
  - same day: second cycle reuses first baseline
  - next day: baseline rotates to new day
  - baseline value not overwritten within same day

### 2) P2: market data freshness aware/naive datetime mismatch

File: `trading/dashboard_api/routes_market_data.py`

Current risk:
- `_is_fresh` uses `datetime.now(UTC)` (aware) while SQLite often returns naive datetimes.
- Subtraction can error and status falls back to `unknown`.

Required fix:
- Normalize timezone semantics before subtraction.
- Choose one consistent approach:
  - normalize both to naive UTC, or
  - normalize both to aware UTC.
- Make `_is_fresh` deterministic for both naive and aware `latest_ts`.

Add tests:
- extend `tests/integration/test_market_data_api.py` and/or add unit tests for `_is_fresh`
- cover both naive and aware timestamp inputs.

### 3) P3: dashboard CORS docs contradiction

File: `dashboard/README.md`

Required fix:
- In CORS troubleshooting section, make wording consistent:
  - both `http://127.0.0.1:5173` and `http://localhost:5173` are valid
  - emphasize matching actual Vite port.
- Remove contradictory sentence that implies `127.0.0.1:5173` is invalid.

## Safety Rules

- No live trading changes
- No order execution logic changes (except risk baseline input correctness)
- No Binance private endpoints
- No API key handling changes
- No bypass of risk controls

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
git add trading/runtime/runner.py trading/dashboard_api/routes_market_data.py tests dashboard/README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "fix: restore daily risk baseline and freshness timezone handling"
```

## Completion Report

Write `docs/claude-tasks/last-result.md` in this format:

```text
# Last Claude Code Result

Task: Fix daily risk baseline + freshness timezone + CORS docs
Status: completed | failed

Files changed:
- ...

Verification:
- ...

Commit:
- ...

Safety:
- No live trading changes.
- No private Binance API changes.
- No API key handling changes.

Notes:
- ...
```

Then stop.

