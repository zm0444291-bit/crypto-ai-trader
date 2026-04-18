from typing import Any, Literal

from pydantic import BaseModel, Field

from trading.strategies.base import TradeCandidate

DecisionHint = Literal["allow", "allow_reduced_size", "reject"]
MarketRegime = Literal["trend", "range", "high_volatility", "unknown"]


class AIScoreRequest(BaseModel):
    candidate: TradeCandidate
    market_context: dict[str, Any]
    portfolio_context: dict[str, Any]


class AIScoreResult(BaseModel):
    ai_score: int = Field(ge=0, le=100)
    market_regime: MarketRegime
    decision_hint: DecisionHint
    risk_flags: list[str]
    explanation: str = Field(min_length=1)
