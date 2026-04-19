# Claude Code Repair Task: Fix Dashboard README CORS Wording

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Fix one documentation inconsistency in `dashboard/README.md`.

Current issue:
- The CORS section says backend allows both `http://127.0.0.1:5173` and `http://localhost:5173`
- But the next line tells users not to use `http://127.0.0.1:5173`

That is contradictory and confusing during troubleshooting.

## Required Change

Edit `dashboard/README.md` CORS section so wording is consistent with backend behavior:

- Both `http://127.0.0.1:5173` and `http://localhost:5173` are valid allowed origins.
- Mention that the critical part is using the actual Vite port shown in startup output.

Keep the section concise and practical.

## Scope

Only edit:
- `dashboard/README.md`
- `docs/claude-tasks/last-result.md`

Do not change code or other docs in this task.

## Verification

Run:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
git status --short
```

## Commit

If verification passes:

```bash
git add dashboard/README.md docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "docs: clarify dashboard CORS troubleshooting guidance"
```

## Completion Report

Write `docs/claude-tasks/last-result.md`:

```text
# Last Claude Code Result

Task: Fix Dashboard README CORS Wording
Status: completed | failed

Files changed:
- ...

Verification:
- ...

Commit:
- ...

Notes:
- ...
```

Then stop.

