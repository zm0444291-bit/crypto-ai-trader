from typing import Any, Protocol

from pydantic import ValidationError

from trading.ai.schemas import AIScoreResult
from trading.strategies.base import TradeCandidate


class AIScoringClient(Protocol):
    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return structured AI scoring output."""


class AIScorer:
    def __init__(self, client: AIScoringClient) -> None:
        self.client = client

    def score_candidate(
        self,
        candidate: TradeCandidate,
        market_context: dict[str, Any],
        portfolio_context: dict[str, Any],
    ) -> AIScoreResult:
        payload = {
            "candidate": candidate.model_dump(mode="json"),
            "market_context": market_context,
            "portfolio_context": portfolio_context,
        }

        try:
            return AIScoreResult.model_validate(self.client.score(payload))
        except (Exception, ValidationError):
            return fail_closed_score()


def fail_closed_score() -> AIScoreResult:
    return AIScoreResult(
        ai_score=0,
        market_regime="unknown",
        decision_hint="reject",
        risk_flags=["ai_error"],
        explanation="AI scoring failed closed.",
    )
