# Claude Code Task: Fix Supervisor Crash Propagation + Docs Consistency

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Fix a high-risk supervisor lifecycle bug:

- If ingestion OR trading thread crashes, supervisor must immediately propagate stop to the other thread and exit deterministically (raise), never hang.

Also fix a small docs inconsistency in root README CORS troubleshooting text.

## Findings To Address

1. `trading/runtime/supervisor.py`
   - In `_ingestion_target` / `_trading_target`, exceptions are captured but `stop` is not set.
   - This can leave the other loop running forever in resident mode and block supervisor shutdown.

2. `README.md`
   - CORS section says whitelist includes both `127.0.0.1:5173` and `localhost:5173`,
     but later text says “Only access localhost”.
   - Align wording so both are valid (port must match Vite output).

## Required Changes

### A) Supervisor crash propagation (must fix)

In `trading/runtime/supervisor.py`:

- When either worker catches an unexpected exception:
  - keep recording `supervisor_component_error`
  - set shared stop event immediately (`stop.set()`)
- Main supervisor loop should then:
  - wait for both threads to finish (reasonable bounded join strategy is fine)
  - raise the captured exception(s) with current behavior (single or combined)
- Ensure `supervisor_stopped` is recorded only after both threads are not alive.
- Keep paper-only behavior unchanged.

### B) Tests (must add/adjust)

Update `tests/unit/test_runtime_supervisor.py`:

- Add a regression test that proves:
  - when one component raises,
  - the other component receives stop signal (not just timeout-exit),
  - supervisor returns/raises without hanging.
- Use synchronization primitives (`Event`) to avoid flaky sleeps.
- Keep all existing tests passing.

### C) README consistency (small fix)

In `/Users/zihanma/Desktop/crypto-ai-trader/README.md` CORS troubleshooting section:

- Replace “Only access localhost...” style wording with wording that clearly states:
  - both `http://127.0.0.1:5173` and `http://localhost:5173` are valid,
  - use the exact host+port shown by Vite.

## Safety Constraints (strict)

- No live trading implementation.
- No private Binance API integration.
- No real API key usage.
- No bypass of risk controls.
- No order execution expansion beyond current paper flow.

## Verification (required)

Run exactly:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/pytest tests/unit/test_runtime_supervisor.py -q
.venv/bin/ruff check trading/runtime/supervisor.py tests/unit/test_runtime_supervisor.py README.md
.venv/bin/pytest -q
.venv/bin/ruff check .
cd dashboard && npm run build && cd ..
git status --short
```

## Commit

If verification passes, commit only relevant files:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
git add trading/runtime/supervisor.py tests/unit/test_runtime_supervisor.py README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "fix: propagate supervisor stop on component crash"
```

## Completion Report

Write `/Users/zihanma/Desktop/crypto-ai-trader/docs/claude-tasks/last-result.md` in this format:

```text
# Last Claude Code Result

Task: Fix Supervisor Crash Propagation + Docs Consistency
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
- Paper-only behavior preserved.

Notes:
- ...
```

Then stop.
