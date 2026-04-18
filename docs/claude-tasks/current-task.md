# Claude Code Task: Milestone 4.1 Risk Profile Foundation

You are the implementation worker for `crypto-ai-trader`.

Read these files first:

- `docs/claude-collaboration.md`
- `docs/superpowers/specs/2026-04-19-crypto-ai-trader-design.md`
- Existing code under `trading/`
- Existing tests under `tests/`

## Goal

Implement the first safe slice of the Risk Engine: risk profile schemas, dynamic equity-based risk limit calculation, daily-loss risk state classification, and tests.

This task is **pre-execution only**. It must not place orders, simulate orders, call Binance private APIs, or change any live trading lock.

## Safety Rules

Do not implement:

- Order execution
- PaperExecutor
- Live trading
- Binance private endpoints
- API key handling
- Position sizing
- Strategy changes
- AI scoring changes
- Runtime scheduler

Do implement:

- Risk profile data models
- Risk state enum/literals
- Daily PnL percentage calculation
- Equity-tier profile selection
- Daily loss classification
- Unit tests

## Files To Create

Create:

- `trading/risk/__init__.py`
- `trading/risk/profiles.py`
- `trading/risk/state.py`
- `tests/unit/test_risk_profiles.py`
- `tests/unit/test_risk_state.py`
- `docs/claude-tasks/last-result.md`

Do not modify unrelated files unless needed for lint or tests.

## Required Behavior

### `trading/risk/profiles.py`

Define:

```python
from decimal import Decimal
from pydantic import BaseModel, Field

class RiskProfile(BaseModel):
    name: str
    equity_min_usdt: Decimal = Field(ge=0)
    equity_max_usdt: Decimal | None = Field(default=None, ge=0)
    daily_loss_caution_pct: Decimal = Field(gt=0)
    daily_loss_no_new_positions_pct: Decimal = Field(gt=0)
    daily_loss_global_pause_pct: Decimal = Field(gt=0)
    max_trade_risk_pct: Decimal = Field(gt=0)
    max_trade_risk_hard_cap_pct: Decimal = Field(gt=0)
    max_symbol_position_pct: Decimal = Field(gt=0)
    max_total_position_pct: Decimal = Field(gt=0)
```

Define:

```python
def default_risk_profiles() -> list[RiskProfile]: ...
def select_risk_profile(equity_usdt: Decimal, profiles: list[RiskProfile] | None = None) -> RiskProfile: ...
def daily_pnl_pct(day_start_equity: Decimal, current_equity: Decimal) -> Decimal: ...
def pct_to_amount(equity_usdt: Decimal, pct: Decimal) -> Decimal: ...
```

Default profiles must match the design:

```text
small_balanced:
  0-1000 USDT
  caution 5
  no_new_positions 7
  global_pause 10
  max_trade_risk 1.5
  hard_cap 2.0
  symbol cap 30
  total cap 70

medium_conservative:
  1000-10000 USDT
  caution 3
  no_new_positions 5
  global_pause 7
  max_trade_risk 1.0
  hard_cap 1.5
  symbol cap 25
  total cap 60

large_conservative:
  10000+ USDT
  caution 2
  no_new_positions 4
  global_pause 5
  max_trade_risk 0.5
  hard_cap 1.0
  symbol cap 20
  total cap 50
```

Rules:

- `select_risk_profile(Decimal("500"))` returns `small_balanced`.
- `select_risk_profile(Decimal("2000"))` returns `medium_conservative`.
- `select_risk_profile(Decimal("20000"))` returns `large_conservative`.
- `daily_pnl_pct(Decimal("100"), Decimal("95")) == Decimal("-5")`.
- `daily_pnl_pct` must raise `ValueError` when day start equity is `<= 0`.
- `pct_to_amount(Decimal("500"), Decimal("7")) == Decimal("35")`.

### `trading/risk/state.py`

Define risk states:

```python
RiskState = Literal["normal", "degraded", "no_new_positions", "global_pause", "emergency_stop"]
```

Define:

```python
class DailyLossDecision(BaseModel):
    risk_state: RiskState
    daily_pnl_pct: Decimal
    reason: str

def classify_daily_loss(day_start_equity: Decimal, current_equity: Decimal, profile: RiskProfile) -> DailyLossDecision: ...
```

Rules for a small profile:

- 0% to above -5% -> `normal`
- -5% to above -7% -> `degraded`
- -7% to above -10% -> `no_new_positions`
- -10% or worse -> `global_pause`

Use positive profile thresholds and compare against losses.

## Required Tests

Write tests that prove:

- Default profile names and thresholds match design.
- Profile selection works for 500, 2000, and 20000 USDT.
- `daily_pnl_pct` calculates loss and gain correctly.
- `daily_pnl_pct` rejects zero day-start equity.
- `pct_to_amount` converts threshold percentages to USDT amount.
- `classify_daily_loss` returns `normal`, `degraded`, `no_new_positions`, and `global_pause` at the expected thresholds.

## Verification Commands

Run:

```bash
.venv/bin/pytest tests/unit/test_risk_profiles.py tests/unit/test_risk_state.py -v
.venv/bin/ruff check trading/risk tests/unit/test_risk_profiles.py tests/unit/test_risk_state.py
.venv/bin/pytest -q
.venv/bin/ruff check .
git status --short
```

## Commit

If all verification passes, commit:

```bash
git add trading/risk tests/unit/test_risk_profiles.py tests/unit/test_risk_state.py docs/claude-tasks/current-task.md docs/claude-tasks/last-result.md
git commit -m "feat: add risk profile foundation"
```

## Completion Report

Write `docs/claude-tasks/last-result.md` with:

```text
# Last Claude Code Result

Task: Milestone 4.1 Risk Profile Foundation
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

