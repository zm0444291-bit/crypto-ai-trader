# Last Claude Code Result

Task: Fix Dashboard README CORS Wording
Status: completed

Files changed:
- dashboard/README.md — rewrote CORS troubleshooting section to remove contradiction: confirmed both `http://127.0.0.1:5173` and `http://localhost:5173` are valid allowed origins; emphasized that the critical part is using the exact URL Vite prints at startup; removed the false constraint that told users not to use `127.0.0.1:5173`
- docs/claude-tasks/current-task.md

Verification:
- `ruff check .` — all checks passed
- `pytest -q` — 174 passed
- `git status --short` — only expected files staged

Commit: 89e2fb0

Notes:
- Previous wording was self-contradictory: line 38 said both origins were allowed, line 40 said "not http://127.0.0.1:5173". This confused users during troubleshooting.
- The backend CORS middleware (trading/main.py) allows `http://127.0.0.1:5173` and `http://localhost:5173` explicitly — both are genuinely valid.
