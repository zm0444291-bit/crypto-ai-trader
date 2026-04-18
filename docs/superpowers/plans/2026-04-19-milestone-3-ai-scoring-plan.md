# Milestone 3 AI Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured AI scoring for rule-generated trade candidates without giving AI authority to create orders or bypass risk controls.

**Architecture:** AI scoring is an injectable service. The scorer builds a deterministic JSON prompt payload, calls a pluggable client, validates structured output, and fails closed when the client errors or returns invalid data. This milestone does not implement RiskEngine, execution, orders, private exchange APIs, or live trading.

**Tech Stack:** Python 3.11+, Pydantic, pytest.

---

## Safety Scope

Allowed:

- AI scoring schemas
- Prompt payload construction
- Injectable client protocol
- Fail-closed scoring behavior
- Unit tests

Forbidden:

- AI-created trades
- Orders or execution
- RiskEngine bypass
- API key storage
- Live trading
- Network calls in tests

## Task 3.1: AI Score Schemas

Files:

- Create `trading/ai/__init__.py`
- Create `trading/ai/schemas.py`
- Create `tests/unit/test_ai_schemas.py`

Models:

- `AIScoreRequest`
- `AIScoreResult`

Rules:

- `ai_score` is integer 0-100.
- `decision_hint` is one of `allow`, `allow_reduced_size`, `reject`.
- `market_regime` is one of `trend`, `range`, `high_volatility`, `unknown`.
- `risk_flags` is a list of strings.
- `explanation` is non-empty.

Verify:

```bash
.venv/bin/pytest tests/unit/test_ai_schemas.py -v
.venv/bin/ruff check trading/ai tests/unit/test_ai_schemas.py
```

Commit:

```bash
git add trading/ai tests/unit/test_ai_schemas.py
git commit -m "feat: add AI scoring schemas"
```

## Task 3.2: AI Scorer

Files:

- Create `trading/ai/scorer.py`
- Create `tests/unit/test_ai_scorer.py`

Implement:

- `AIScoringClient` protocol with `score(payload: dict[str, Any]) -> dict[str, Any]`
- `AIScorer.score_candidate(...) -> AIScoreResult`
- Fail closed on client exception or invalid response.

Fail-closed result:

```text
ai_score = 0
decision_hint = reject
market_regime = unknown
risk_flags includes "ai_error"
```

Verify:

```bash
.venv/bin/pytest tests/unit/test_ai_scorer.py -v
.venv/bin/ruff check trading/ai tests/unit/test_ai_scorer.py
```

Commit:

```bash
git add trading/ai/scorer.py tests/unit/test_ai_scorer.py
git commit -m "feat: add fail-closed AI scorer"
```

## Final Verification

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
git status --short
```

