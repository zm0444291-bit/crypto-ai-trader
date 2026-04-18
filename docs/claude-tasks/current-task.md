# Claude Code Task: Milestone 4.2 Pre-Trade Risk Checks

You are the implementation worker for `crypto-ai-trader`.

Read:

- `docs/claude-collaboration.md`
- `trading/risk/profiles.py`
- `trading/risk/state.py`
- `trading/strategies/base.py`
- Existing tests under `tests/unit/`

## Goal

Implement deterministic pre-trade risk checks for a `TradeCandidate`. This task must only approve or reject a candidate. It must not size positions, create orders, simulate fills, call Binance, or touch live trading.

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

- `trading/risk/pre_trade.py`
- `tests/unit/test_pre_trade_risk.py`
- `docs/claude-tasks/last-result.md`

## Required Models

Create in `trading/risk/pre_trade.py`:

```python
from decimal import Decimal
from pydantic import BaseModel

class PortfolioRiskSnapshot(BaseModel):
    account_equity: Decimal
    day_start_equity: Decimal
    total_position_pct: Decimal
    symbol_position_pct: Decimal
    open_positions: int
    daily_order_count: int
    symbol_daily_trade_count: int
    consecutive_losses: int
    data_is_fresh: bool
    kill_switch_enabled: bool

class PreTradeRiskDecision(BaseModel):
    approved: bool
    risk_state: RiskState
    size_multiplier: Decimal
    reject_reasons: list[str]
```

Create:

```python
def evaluate_pre_trade_risk(
    candidate: TradeCandidate,
    snapshot: PortfolioRiskSnapshot,
    profile: RiskProfile,
    max_daily_orders: int = 15,
    max_symbol_daily_trades: int = 4,
    max_consecutive_losses: int = 4,
) -> PreTradeRiskDecision: ...
```

## Required Behavior

Reject when:

- kill switch is enabled
- data is not fresh
- daily loss state is `no_new_positions` or `global_pause`
- total position pct is greater than or equal to profile max total position pct
- symbol position pct is greater than or equal to profile max symbol position pct
- daily order count is greater than or equal to max daily orders
- symbol daily trade count is greater than or equal to max symbol daily trades
- consecutive losses is greater than or equal to max consecutive losses

Approve when none of the reject rules apply.

Risk state:

- Use `classify_daily_loss`.
- If approved and daily loss state is `degraded`, return `risk_state="degraded"` and `size_multiplier=Decimal("0.5")`.
- If approved and daily loss state is `normal`, return `risk_state="normal"` and `size_multiplier=Decimal("1")`.
- If rejected by kill switch, return `risk_state="emergency_stop"`.
- If rejected by daily loss no-new/global, return that daily loss risk state.
- Otherwise rejected risk state can be `no_new_positions`.

Reject reason strings must be stable snake_case codes, such as:

- `kill_switch_enabled`
- `stale_market_data`
- `daily_loss_no_new_positions`
- `daily_loss_global_pause`
- `max_total_position_reached`
- `max_symbol_position_reached`
- `max_daily_orders_reached`
- `max_symbol_daily_trades_reached`
- `max_consecutive_losses_reached`

## Required Tests

Write unit tests for:

- approves normal candidate with size multiplier 1
- degraded daily loss approves with size multiplier 0.5
- kill switch rejects with emergency_stop
- stale data rejects
- no_new_positions daily loss rejects
- global_pause daily loss rejects
- max total position rejects
- max symbol position rejects
- max daily orders rejects
- max symbol daily trades rejects
- max consecutive losses rejects

## Verification

Run:

```bash
.venv/bin/pytest tests/unit/test_pre_trade_risk.py -v
.venv/bin/ruff check trading/risk tests/unit/test_pre_trade_risk.py
.venv/bin/pytest -q
.venv/bin/ruff check .
git status --short
```

## Commit

If verification passes:

```bash
git add trading/risk/pre_trade.py tests/unit/test_pre_trade_risk.py docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add pre-trade risk checks"
```

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Milestone 4.2 Pre-Trade Risk Checks
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
