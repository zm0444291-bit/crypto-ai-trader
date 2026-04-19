"""Dashboard API routes for market data."""

from datetime import UTC, datetime

from fastapi import APIRouter

from trading.market_data.candle_service import SYMBOLS, TIMEFRAMES, MarketDataStatus
from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import CandlesRepository

router = APIRouter(tags=["market-data"])

# Timeframe thresholds in seconds — a candle is considered stale after 2x this window
_STALE_THRESHOLD_SECONDS: dict[str, int] = {
    "15m": 1800,
    "1h": 7200,
    "4h": 28800,
}


def _is_fresh(latest_ts: datetime | None, timeframe: str) -> bool:
    if latest_ts is None:
        return False
    now = datetime.now(UTC)
    threshold = _STALE_THRESHOLD_SECONDS.get(timeframe, 3600)
    return (now - latest_ts).total_seconds() < threshold


def _build_market_data_status() -> MarketDataStatus:
    try:
        settings = AppSettings()
        engine = create_database_engine(settings.database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = CandlesRepository(session)
            latest: dict[str, datetime | None] = {}
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    candle = repo.get_latest(symbol, tf)
                    latest[f"{symbol}/{tf}"] = (
                        candle.open_time if candle else None
                    )

        latest_times = [latest.get(f"{s}/{tf}") for s in SYMBOLS for tf in TIMEFRAMES]
        any_fresh = any(_is_fresh(ts, tf) for tf in TIMEFRAMES for ts in latest_times)
        status_value = "fresh" if any_fresh else "stale"

        return MarketDataStatus(
            symbols=SYMBOLS,
            timeframes=TIMEFRAMES,
            status=status_value,
            live_trading_enabled=False,
        )
    except Exception:
        # Resilience: if DB is unavailable, return safe defaults
        return MarketDataStatus(
            symbols=SYMBOLS,
            timeframes=TIMEFRAMES,
            status="unknown",
            live_trading_enabled=False,
        )


@router.get("/market-data/status", response_model=MarketDataStatus)
def read_market_data_status() -> MarketDataStatus:
    """Return market data status with configured symbols and timeframes.

    Includes a high-level status: 'fresh' if at least one candle is recent,
    'stale' if candles exist but none are fresh, 'unknown' if the database
    is unavailable.
    """

    return _build_market_data_status()
