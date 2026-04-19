# Claude Code Task: Milestone 4.3 Position Sizing

You are the implementation worker for `crypto-ai-trader`.

Read:

- `docs/claude-collaboration.md`
- `trading/risk/profiles.py`
- `trading/risk/pre_trade.py`
- `trading/strategies/base.py`
- Existing tests under `tests/unit/`

## Goal

Implement deterministic position sizing for an approved `TradeCandidate`. This task must calculate a notional USDT order size only. It must not create orders, simulate fills, call exchanges, read account balances from Binance, or touch live trading.

## Safety Rules

Do not implement:

- Order execution
- PaperExecutor
- Live trading
- Binance private endpoints
- API key handling
- Runtime scheduler
- Exchange account reads

## Files To Create

- `trading/risk/position_sizing.py`
- `tests/unit/test_position_sizing.py`
- `docs/claude-tasks/last-result.md`

## Required Models

Create in `trading/risk/position_sizing.py`:

```python
from decimal import Decimal
from pydantic import BaseModel

class PositionSizeResult(BaseModel):
    approved: bool
    notional_usdt: Decimal
    max_loss_usdt: Decimal
    reject_reasons: list[str]
```

Create:

```python
def calculate_position_size(
    candidate: TradeCandidate,
    pre_trade_decision: PreTradeRiskDecision,
    profile: RiskProfile,
    account_equity: Decimal,
    min_notional_usdt: Decimal = Decimal("10"),
) -> PositionSizeResult: ...
```

## Required Behavior

- If `pre_trade_decision.approved` is false, return approved false, notional 0, max_loss 0, and include `pre_trade_rejected`.
- Risk per trade is `account_equity * profile.max_trade_risk_pct / 100`.
- Hard cap is `account_equity * profile.max_trade_risk_hard_cap_pct / 100`; max loss must not exceed hard cap.
- Stop distance is `entry_reference - stop_reference`.
- Reject if stop distance is <= 0 with `invalid_stop_distance`.
- Raw notional is `max_loss_usdt / (stop_distance / entry_reference)`.
- Apply `pre_trade_decision.size_multiplier`.
- Cap notional at `account_equity * profile.max_symbol_position_pct / 100`.
- Reject if final notional is below `min_notional_usdt` with `below_min_notional`.
- Return approved true with final notional and max_loss_usdt when all checks pass.

Use `Decimal` throughout.

## Required Tests

Write unit tests for:

- returns notional for normal approved trade
- applies degraded size multiplier
- caps by max symbol position percentage
- rejects pre-trade rejected decision
- rejects invalid stop distance
- rejects below min notional
- hard cap prevents max loss exceeding hard cap

## Verification

Run:

```bash
.venv/bin/pytest tests/unit/test_position_sizing.py -v
.venv/bin/ruff check trading/risk tests/unit/test_position_sizing.py
.venv/bin/pytest -q
.venv/bin/ruff check .
git status --short
```

## Commit

If verification passes:

```bash
git add trading/risk/position_sizing.py tests/unit/test_position_sizing.py docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add deterministic position sizing"
```

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Milestone 4.3 Position Sizing
Status: completed | failed

Files changed:
- ...

Verification:
- ...

Commit:
- ...

Safety:
- No order execution added.
- No private Binance API added.
- No API key handling added.
- No live trading added.

Notes:
- ...
```

Then stop.
