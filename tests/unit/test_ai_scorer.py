from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading.ai.scorer import AIScorer
from trading.strategies.base import TradeCandidate


class SuccessfulClient:
    def __init__(self) -> None:
        self.last_payload: dict[str, Any] | None = None

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_payload = payload
        return {
            "ai_score": 78,
            "market_regime": "trend",
            "decision_hint": "allow",
            "risk_flags": ["volatility_elevated"],
            "explanation": "Momentum is aligned.",
        }


class FailingClient:
    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("model unavailable")


class InvalidClient:
    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ai_score": 999}


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


def test_ai_scorer_returns_valid_client_result_and_payload():
    client = SuccessfulClient()
    scorer = AIScorer(client)

    result = scorer.score_candidate(
        candidate=make_candidate(),
        market_context={"trend_state": "up"},
        portfolio_context={"risk_state": "normal"},
    )

    assert result.ai_score == 78
    assert result.decision_hint == "allow"
    assert client.last_payload is not None
    assert client.last_payload["candidate"]["symbol"] == "BTCUSDT"
    assert client.last_payload["market_context"] == {"trend_state": "up"}


def test_ai_scorer_fails_closed_on_client_exception():
    scorer = AIScorer(FailingClient())

    result = scorer.score_candidate(
        candidate=make_candidate(),
        market_context={},
        portfolio_context={},
    )

    assert result.ai_score == 0
    assert result.decision_hint == "reject"
    assert result.market_regime == "unknown"
    assert "ai_error" in result.risk_flags


def test_ai_scorer_fails_closed_on_invalid_client_response():
    scorer = AIScorer(InvalidClient())

    result = scorer.score_candidate(
        candidate=make_candidate(),
        market_context={},
        portfolio_context={},
    )

    assert result.ai_score == 0
    assert result.decision_hint == "reject"
    assert "ai_error" in result.risk_flags
