# Claude Code Task: Unified Local Supervisor (Ingestion + Trading Loops)

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Create a single local supervisor that can run both:
1) market data ingestion loop
2) paper trading runtime loop

in one command, with clean startup/shutdown and clear event visibility.

This should improve local operability while staying strictly paper-only.

## Read First

- `trading/runtime/runner.py`
- `trading/runtime/cli.py`
- `trading/market_data/ingestion_runner.py`
- `trading/storage/repositories.py`
- `trading/main.py`
- `README.md`
- `Makefile`

## Requirements

1. Create module:
   - `trading/runtime/supervisor.py`

2. Implement:
   - `run_supervisor(...)` that starts ingestion loop and trading loop concurrently
   - Use threads (or another simple in-process concurrency model) with shared stop signal
   - Graceful shutdown on KeyboardInterrupt:
     - stop signal set
     - both loops joined with timeout
     - supervisor exit event recorded

3. Event logging:
   - record:
     - `supervisor_started`
     - `supervisor_stopped`
     - `supervisor_component_error` (if any loop crashes unexpectedly)
   - include structured context with intervals and symbols

4. CLI integration:
   - extend `trading/runtime/cli.py` with a new mode:
     - `python -m trading.runtime.cli --supervisor`
   - add optional flags:
     - `--ingest-interval` (default 300)
     - `--trade-interval` (default 300)
     - `--max-cycles` (optional, passed to both loops for bounded test runs)

5. Keep existing modes working:
   - `--once`
   - `--interval`
   - no behavior regressions

6. Add Makefile convenience target:
   - `runtime-supervisor`
   - uses `.venv/bin/python -m trading.runtime.cli --supervisor ...`

7. Update docs:
   - `README.md` quickstart: add supervisor mode as the preferred "single terminal" runtime option
   - keep paper-only safety wording

## Safety Constraints

- No live trading
- No private Binance endpoints
- No API key handling changes
- No trading execution behavior expansion beyond existing paper flow
- No write APIs in dashboard

## Tests

Add unit tests:
- `tests/unit/test_runtime_supervisor.py`

Cover at least:
1. starts both components with expected arguments
2. KeyboardInterrupt/shutdown sets stop signal and joins threads
3. component exception records `supervisor_component_error` and exits safely
4. existing CLI modes (`--once`, `--interval`) still parse and run path selection correctly

If needed, add focused tests in `tests/unit/test_runtime_cli.py`.

## Verification (required)

Run:

```bash
.venv/bin/pytest tests/unit/test_runtime_supervisor.py -q
.venv/bin/ruff check trading/runtime/supervisor.py trading/runtime/cli.py tests/unit/test_runtime_supervisor.py
.venv/bin/pytest -q
.venv/bin/ruff check .
cd dashboard && npm run build
cd ..
git status --short
```

## Commit

If verification passes:

```bash
git add trading/runtime/supervisor.py trading/runtime/cli.py tests/unit/test_runtime_supervisor.py Makefile README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add unified local runtime supervisor"
```

## Completion Report

Write `docs/claude-tasks/last-result.md`:

```text
# Last Claude Code Result

Task: Unified Local Supervisor (Ingestion + Trading Loops)
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

