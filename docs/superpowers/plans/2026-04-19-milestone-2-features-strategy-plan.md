# Milestone 2 Features And Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic feature calculation and a rule-only multi-timeframe momentum strategy that creates traceable trade candidates.

**Architecture:** This milestone stays pre-trade. It calculates indicators from stored candles and emits candidate signals, but does not call AI, apply risk decisions, size positions, execute orders, or use private exchange APIs.

**Tech Stack:** Python 3.11+, Pydantic, SQLAlchemy, pytest.

---

## Safety Scope

Allowed:

- Indicator calculations
- Feature DTOs
- Strategy candidate DTOs
- Long-only rule-generated candidate signals
- Unit tests

Forbidden:

- AI scoring
- RiskEngine
- Position sizing
- Orders
- PaperExecutor
- Live trading
- Binance private API
- API keys

## Task 2.1: Indicator Functions

**Files:**

- Create: `trading/features/__init__.py`
- Create: `trading/features/indicators.py`
- Create: `tests/unit/test_indicators.py`

Implement:

```python
def ema(values: list[Decimal], period: int) -> list[Decimal | None]: ...
def rsi(values: list[Decimal], period: int = 14) -> list[Decimal | None]: ...
def true_range(high: Decimal, low: Decimal, previous_close: Decimal | None) -> Decimal: ...
def atr(highs: list[Decimal], lows: list[Decimal], closes: list[Decimal], period: int = 14) -> list[Decimal | None]: ...
```

Requirements:

- Use `Decimal`.
- Return a list the same length as input.
- Return `None` until enough data exists.
- Raise `ValueError` for invalid period or mismatched OHLC lengths.

Tests:

- EMA returns same length and first valid value at `period - 1`.
- RSI returns values between 0 and 100 once valid.
- true range handles missing previous close.
- ATR rejects mismatched lengths.

Verify:

```bash
.venv/bin/pytest tests/unit/test_indicators.py -v
.venv/bin/ruff check trading/features tests/unit/test_indicators.py
```

Commit:

```bash
git add trading/features tests/unit/test_indicators.py
git commit -m "feat: add indicator calculations"
```

## Task 2.2: Feature Builder

**Files:**

- Create: `trading/features/builder.py`
- Create: `tests/unit/test_feature_builder.py`

Implement:

```python
class CandleFeatures(BaseModel):
    symbol: str
    timeframe: str
    candle_time: datetime
    close: Decimal
    ema_fast: Decimal | None
    ema_slow: Decimal | None
    ema_200: Decimal | None
    rsi_14: Decimal | None
    atr_14: Decimal | None
    volume_ratio: Decimal | None
    trend_state: Literal["up", "down", "neutral", "unknown"]


def build_features(candles: list[CandleData]) -> list[CandleFeatures]: ...
```

Rules:

- Preserve candle order by `open_time`.
- `ema_fast` uses period 12.
- `ema_slow` uses period 26.
- `ema_200` uses period 200.
- `volume_ratio` is current volume divided by average volume of prior 20 candles.
- `trend_state = "up"` when close > ema_slow and ema_fast > ema_slow.
- `trend_state = "down"` when close < ema_slow and ema_fast < ema_slow.
- Otherwise `neutral`; if missing EMA, `unknown`.

Verify:

```bash
.venv/bin/pytest tests/unit/test_feature_builder.py -v
.venv/bin/ruff check trading/features tests/unit/test_feature_builder.py
```

Commit:

```bash
git add trading/features/builder.py tests/unit/test_feature_builder.py
git commit -m "feat: add feature builder"
```

## Task 2.3: Strategy Candidate Model And Momentum Strategy

**Files:**

- Create: `trading/strategies/__init__.py`
- Create: `trading/strategies/base.py`
- Create: `trading/strategies/active/__init__.py`
- Create: `trading/strategies/active/multi_timeframe_momentum.py`
- Create: `tests/unit/test_multi_timeframe_momentum.py`

Implement:

```python
class TradeCandidate(BaseModel):
    strategy_name: str
    symbol: str
    side: Literal["BUY"]
    entry_reference: Decimal
    stop_reference: Decimal
    rule_confidence: Decimal
    reason: str
    created_at: datetime


def generate_momentum_candidate(
    symbol: str,
    features_15m: list[CandleFeatures],
    features_1h: list[CandleFeatures],
    features_4h: list[CandleFeatures],
    now: datetime,
) -> TradeCandidate | None: ...
```

Candidate rules:

- Need at least one latest feature in each timeframe.
- 4h trend must not be `"down"`.
- 1h trend must be `"up"`.
- 15m trend must be `"up"`.
- Latest 15m close must be above latest 15m EMA fast.
- ATR must exist on 15m; stop is `entry_reference - (atr_14 * 2)`.
- `rule_confidence` is `0.70` for normal candidate.
- Return `None` when any rule fails.

Verify:

```bash
.venv/bin/pytest tests/unit/test_multi_timeframe_momentum.py -v
.venv/bin/ruff check trading/strategies tests/unit/test_multi_timeframe_momentum.py
```

Commit:

```bash
git add trading/strategies tests/unit/test_multi_timeframe_momentum.py
git commit -m "feat: add momentum trade candidate strategy"
```

## Task 2.4: Final Verification

Run:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -v
git status --short
```

Expected:

- Ruff passes.
- Pytest passes.
- Worktree is clean after commits.

## Worker Report

Report:

```text
Milestone 2 status:
- Tasks completed:
- Commits:
- Verification:
- Safety: no AI, risk, execution, private API, or live trading code added.
```

