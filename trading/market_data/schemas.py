from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CandleData(BaseModel):
    """Normalized OHLCV candle from an exchange."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    source: str = "binance"
