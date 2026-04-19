# Last Claude Code Result

Task: Fix daily risk baseline + freshness timezone + CORS docs
Status: completed

Files changed:
- `trading/runtime/runner.py`: Added `_get_or_create_day_baseline()` that persists the daily equity baseline via a `day_baseline_set` event in the DB. On first cycle of a UTC day a new baseline is created from current equity; on subsequent cycles the stored baseline is reused. `_build_cycle_inputs` now calls this instead of setting `day_start_equity = account_equity`.
- `trading/dashboard_api/routes_market_data.py`: `_is_fresh()` now normalizes naive datetimes to aware UTC before the subtraction, preventing `TypeError` when SQLite returns naive timestamps.
- `dashboard/README.md`: Clarified CORS troubleshooting section — both `127.0.0.1:5173` and `localhost:5173` are equally valid; removed contradictory wording.

Verification:
- `ruff check trading/runtime/runner.py trading/dashboard_api/routes_market_data.py dashboard/README.md` — all passed
- `cd dashboard && npm run build` — built in 246ms
- `.venv/bin/pytest -q` — 185 passed
- `git status --short` — clean (only expected files modified)

Commit:
- (pending)

Safety:
- No live trading changes.
- No private Binance API changes.
- No API key handling changes.
- No bypass of risk controls.

Notes:
- Baseline is keyed by UTC date string in event context; any existing `day_baseline_set` event from a previous day is ignored and a fresh baseline is created.
- `_is_fresh` handles both naive and aware datetimes by normalising the input to aware UTC before comparison.
