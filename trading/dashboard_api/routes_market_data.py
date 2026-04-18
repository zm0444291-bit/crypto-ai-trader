"""Dashboard API routes for market data."""

from fastapi import APIRouter

from trading.market_data.candle_service import MarketDataStatus, get_market_data_status

router = APIRouter(tags=["market-data"])


@router.get("/market-data/status", response_model=MarketDataStatus)
def read_market_data_status() -> MarketDataStatus:
    """Return market data status with configured symbols and timeframes."""

    return get_market_data_status()