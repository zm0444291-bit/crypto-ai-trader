"""Base types for strategy signals."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class MarketRegime(StrEnum):
    """Market regime classified by the MarketRegimeDetector."""

    TREND = "trend"  # Strong directional move (ADX > 25, BB bandwidth high)
    RANGE = "range"  # Ranging / mean-reverting (ADX < 20, BB bandwidth low)
    VOLATILE = "volatile"  # High volatility but unclear direction


class TradeCandidate(BaseModel):
    """A candidate signal produced by a strategy."""

    strategy_name: str
    symbol: str
    side: Literal["BUY"]
    entry_reference: Decimal = Field(gt=0)
    stop_reference: Decimal = Field(gt=0)
    rule_confidence: Decimal = Field(ge=0, le=1)
    reason: str
    created_at: datetime


@dataclass
class Signal:
    """A trade signal produced by any strategy.

    Attributes
    ----------
    side : str
        "buy" or "sell".
    qty : Decimal
        Quantity to trade.
    entry_atr : float | None
        Optional ATR value at signal generation (used for stop/target sizing).
    """

    qty: Decimal
    side: str
    entry_atr: float | None = None
