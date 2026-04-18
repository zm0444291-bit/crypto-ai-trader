from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading.ai.schemas import AIScoreRequest, AIScoreResult
from trading.strategies.base import TradeCandidate


def make_candidate() -> TradeCandidate:
    return TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("100"),
        stop_reference=Decimal("96"),
        rule_confidence=Decimal("0.70"),
        reason="Momentum aligned.",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def test_ai_score_request_wraps_candidate_and_context():
    request = AIScoreRequest(
        candidate=make_candidate(),
        market_context={"trend_state": "up"},
        portfolio_context={"risk_state": "normal"},
    )

    assert request.candidate.symbol == "BTCUSDT"
    assert request.market_context == {"trend_state": "up"}
    assert request.portfolio_context == {"risk_state": "normal"}


def test_ai_score_result_accepts_valid_structured_output():
    result = AIScoreResult(
        ai_score=78,
        market_regime="trend",
        decision_hint="allow",
        risk_flags=["volatility_elevated"],
        explanation="Momentum is aligned across timeframes.",
    )

    assert result.ai_score == 78
    assert result.decision_hint == "allow"


def test_ai_score_result_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        AIScoreResult(
            ai_score=101,
            market_regime="trend",
            decision_hint="allow",
            risk_flags=[],
            explanation="Invalid score.",
        )


def test_ai_score_result_rejects_empty_explanation():
    with pytest.raises(ValidationError):
        AIScoreResult(
            ai_score=50,
            market_regime="unknown",
            decision_hint="reject",
            risk_flags=[],
            explanation="",
        )
