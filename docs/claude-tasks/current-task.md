# Claude Code Task: Execution Gate + LiveTradingLock (Paper-Only Control Plane)

You are the implementation worker for `/Users/zihanma/Desktop/crypto-ai-trader`.

## Goal

Implement an explicit execution control plane that sits between strategy/risk outputs and executors:

1. `ExecutionGate` (mode-aware routing decision)
2. `LiveTradingLock` (hard lock to prevent accidental live routing)
3. runtime mode state model (`paused`, `paper_auto`, `live_shadow`, `live_small_auto`) with strict transition rules

This milestone must remain **paper-only in behavior**. No real order submission.

## Read First

- `/Users/zihanma/Desktop/crypto-ai-trader/trading/runtime/paper_cycle.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/runtime/runner.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/execution/paper_executor.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/risk/pre_trade.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/main.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/dashboard_api/routes_runtime.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/storage/models.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/trading/storage/repositories.py`
- `/Users/zihanma/Desktop/crypto-ai-trader/docs/superpowers/specs/2026-04-19-crypto-ai-trader-design.md` (Execution Gate + mode sections)

## Required Scope

### 1) New execution control module

Create `trading/execution/gate.py` with:

- `TradeMode` literal/enum:
  - `paused`
  - `paper_auto`
  - `live_shadow`
  - `live_small_auto`
- `ExecutionDecision` model:
  - `allowed: bool`
  - `route: str` (`paper`, `shadow`, `blocked`)
  - `reason: str`
  - `mode: TradeMode`
- `LiveTradingLock` model:
  - `enabled: bool` (default false)
  - optional `reason`
- `ExecutionGate` class/function:
  - inputs: current mode, lock state, risk state, kill switch, candidate/order context
  - outputs: `ExecutionDecision`

Decision policy (strict):

- `paused` => blocked
- `paper_auto` => allow `paper` only when risk/kill-switch pass
- `live_shadow` => allow `shadow` only (no exchange order execution)
- `live_small_auto` => **blocked unless explicit live unlock flag is true**; for this milestone keep blocked by default
- any kill switch or emergency/global pause => blocked

### 2) Mode transition validator

Create `trading/runtime/mode.py` with:

- mode transition function `validate_mode_transition(from_mode, to_mode, lock_state, allow_live_unlock=False)`
- enforce:
  - no direct `paused -> live_small_auto`
  - no `paper_auto -> live_small_auto` without passing through `live_shadow`
  - `live_small_auto` requires explicit unlock flag + lock enabled

Return structured result (`allowed`, `reason`) and use it in runtime control paths (read-only visibility is enough if no write API exists yet).

### 3) Integrate gate into paper cycle path

Update cycle orchestration so execution decision is explicit:

- after risk + position sizing pass, call `ExecutionGate`
- only execute paper order when decision route is `paper`
- if blocked, record event with structured context:
  - mode
  - decision reason
  - risk state
  - lock state

No behavior regression for current `paper_auto` default.

### 4) Runtime status visibility

Extend runtime status response to include:

- `trade_mode` (current mode, default `paper_auto`)
- `live_trading_lock_enabled` (bool)
- `execution_route_effective` (expected route for current mode: `paper`/`shadow`/`blocked`)
- `mode_transition_guard` (string summary, optional)

Safe defaults required when data missing.

### 5) Dashboard visibility (read-only)

Update Overview and/or Settings page to show:

- current mode
- live lock enabled/disabled
- effective execution route
- clear paper-only notice remains visible

No UI controls that can place orders.

## Safety Constraints (strict)

- No real exchange order execution.
- No private Binance API integration.
- No API key handling changes for live trading.
- Do not bypass RiskEngine / kill switch.
- Do not implement write endpoints that switch to live mode.
- Preserve existing paper execution behavior.

## Tests (required)

Add/extend tests for:

1. gate decisions per mode:
   - paused blocked
   - paper_auto routes to paper
   - live_shadow routes to shadow
   - live_small_auto blocked by default
2. lock/risk/kill-switch overrides
3. mode transition validator rules
4. paper cycle integration:
   - gate blocked path does not execute order and records event
5. runtime status returns new fields with safe defaults

Suggested files:

- `tests/unit/test_execution_gate.py` (new)
- `tests/unit/test_runtime_mode.py` (new)
- `tests/unit/test_paper_cycle.py` (extend)
- `tests/integration/test_runtime_status_api.py` (extend)

## Verification (required)

Run exactly:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
.venv/bin/ruff check .
.venv/bin/pytest -q
cd /Users/zihanma/Desktop/crypto-ai-trader/dashboard
npm run build
cd /Users/zihanma/Desktop/crypto-ai-trader
git status --short
```

## Commit

If verification passes:

```bash
cd /Users/zihanma/Desktop/crypto-ai-trader
git add trading/execution trading/runtime trading/dashboard_api dashboard/src tests docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add execution gate and live trading lock control plane"
```

## Completion Report

Write `/Users/zihanma/Desktop/crypto-ai-trader/docs/claude-tasks/last-result.md` with:

- task
- status
- files changed
- verification summary
- commit hash
- safety checklist confirmation

Then stop.
