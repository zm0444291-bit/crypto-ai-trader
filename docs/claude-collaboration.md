# Claude Code Collaboration Rules

This project uses a controller-worker collaboration model.

Controller:

- Owns architecture, task sequencing, review, and risk boundaries.
- Writes implementation plans before coding starts.
- Reviews Claude Code output before the next task begins.

Claude Code worker:

- Implements only the assigned task.
- Runs the exact verification commands from the plan.
- Stops after the assigned task and reports changes, tests, and blockers.

## Hard Rules

1. Do not implement live trading unless the active task explicitly requests it.
2. Do not create, request, print, store, or commit real API keys.
3. Do not bypass `ExecutionGate`, `RiskEngine`, `LiveTradingLock`, or `KillSwitch`.
4. Do not change the approved system design without a review note.
5. Do not implement future extension templates beyond stubs unless explicitly assigned.
6. Do not continue into the next task automatically.
7. Do not delete unrelated files.
8. Do not commit `.env`, database files, logs, caches, or local runtime artifacts.

## Worker Completion Report

Each Claude Code run must finish with:

- Files created or changed
- Verification commands run
- Test results
- Known issues or skipped checks
- Whether a git commit was created

## Dispatch Template

Use this prompt when assigning work:

```text
You are the implementation worker for crypto-ai-trader.

Read:
- docs/claude-collaboration.md
- docs/superpowers/specs/2026-04-19-crypto-ai-trader-design.md
- docs/superpowers/plans/2026-04-19-milestone-0-project-skeleton-plan.md

Execute only the assigned task: [TASK NAME].

Follow the plan exactly. Do not implement later tasks. Do not add live trading behavior. Do not create or commit real secrets. Run the specified verification commands. Stop when the assigned task is complete and report files changed, commands run, test results, and blockers.
```

