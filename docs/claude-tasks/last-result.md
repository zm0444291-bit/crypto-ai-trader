# Last Claude Code Result

Task: Dashboard Partial API Failure Visibility
Status: completed

Files changed:
- dashboard/src/App.tsx (per-panel failure tracking)
- docs/claude-tasks/last-result.md (updated)

Verification:
- `cd dashboard && npm run build` — succeeded (tsc + vite build, 243ms)
- `ruff check .` — all checks passed
- `pytest -q` — 148 passed in 0.43s
- `git status --short` — clean (only App.tsx and current-task.md)

Commit:
- `git add dashboard/src/App.tsx docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md`
- `git commit -m "fix: show dashboard partial API failures"`

Safety:
- No order execution added.
- No private Binance API added.
- No API key handling added.
- No live trading added.
- Dashboard remains read-only.

Notes:
- Replaced `offline = !health && !risk && ...` with per-panel `failures` state.
- `hasApiFailure = Object.values(failures).some(Boolean)` drives the offline notice.
- Each panel receives null/placeholder only when its own API failed, preserving real data from successful calls.
- EventsSection shows placeholder event when `/events/recent` itself fails.
