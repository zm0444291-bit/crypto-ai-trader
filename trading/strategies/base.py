from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TradeCandidate(BaseModel):
    strategy_name: str
    symbol: str
    side: Literal["BUY"]
    entry_reference: Decimal = Field(gt=0)
    stop_reference: Decimal = Field(gt=0)
    rule_confidence: Decimal = Field(ge=0, le=1)
    reason: str
    created_at: datetime
