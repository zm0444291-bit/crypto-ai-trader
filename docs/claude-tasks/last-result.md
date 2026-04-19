# Last Claude Code Result

Task: Dashboard Partial API Failure Visibility — granular per-panel failure flags
Status: completed

Files changed:
- dashboard/src/App.tsx (granular failure props for StatusStrip and MetricsGrid)

Verification:
- `cd dashboard && npm run build` — succeeded
- `ruff check .` — all checks passed
- `pytest -q` — 148 passed

Commit:
- `git add dashboard/src/App.tsx`
- `git commit -m "fix: use granular failure flags for StatusStrip and MetricsGrid"`

Safety:
- No order execution added.
- No private Binance API added.
- No API key handling added.
- No live trading added.
- Dashboard remains read-only.

Notes:
- StatusStrip now uses `healthFailed` and `riskFailed` instead of global `isOffline`.
- MetricsGrid now uses `riskFailed` and `portfolioFailed` instead of global `isOffline`.
- Each panel falls back independently based on its own relevant API failures.
