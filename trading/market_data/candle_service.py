"""Market data service - DTOs and business logic for candle data."""

from pydantic import BaseModel


class MarketDataStatus(BaseModel):
    """API response for market data status."""

    symbols: list[str]
    timeframes: list[str]
    status: str
    live_trading_enabled: bool


# Static configuration for Milestone 1
# In future milestones, this will be driven by database or dynamic config
SYMBOLS: list[str] = ["XAUUSD"]
TIMEFRAMES: list[str] = ["15m", "1h", "4h"]


def get_market_data_status() -> MarketDataStatus:
    """Return static market data status (no Binance calls)."""

    return MarketDataStatus(
        symbols=SYMBOLS,
        timeframes=TIMEFRAMES,
        status="configured",
        live_trading_enabled=False,
    )