# Last Claude Code Result

Task: Fix Supervisor Crash Propagation + Docs Consistency
Status: completed

Files changed:
- `trading/runtime/supervisor.py` — Added `stop.set()` in both `_ingestion_target` and `_trading_target` exception handlers so the other thread exits promptly when one crashes.
- `tests/unit/test_runtime_supervisor.py` — Added `test_stop_set_called_when_component_crashes` regression test proving stop is set immediately on crash (elapsed < 0.5s assertion).
- `README.md` — Fixed CORS troubleshooting wording: both `http://127.0.0.1:5173` and `http://localhost:5173` are valid origins.
- `docs/claude-tasks/current-task.md` — Updated as part of task tracking.

Verification:
- `.venv/bin/ruff check trading/runtime/supervisor.py tests/unit/test_runtime_supervisor.py README.md` — all passed
- `.venv/bin/pytest tests/unit/test_runtime_supervisor.py -q` — 15 passed
- `.venv/bin/pytest -q` — 207 passed
- `.venv/bin/ruff check .` — all passed
- `cd dashboard && npm run build` — built in 247ms, no errors

Commit:
- `f4e8d53` fix: propagate supervisor stop on component crash

Safety:
- No live trading changes.
- No private Binance API changes.
- No API key handling changes.
- Paper-only behavior preserved.

Notes:
- Supervisor now calls `stop.set()` immediately in both exception handlers, ensuring the other thread exits without hanging.
- New regression test uses elapsed-time measurement (asserts < 0.5s) to prove stop signal propagates promptly.
- All existing tests continue to pass.
