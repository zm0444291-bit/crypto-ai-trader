from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy.orm import Session

from trading.dashboard_api.routes_health import router as health_router
from trading.dashboard_api.routes_market_data import router as market_data_router
from trading.dashboard_api.routes_orders import router as orders_router
from trading.storage.repositories import EventsRepository

app = FastAPI(title="Crypto AI Trader")
app.include_router(health_router)
app.include_router(market_data_router)
app.include_router(orders_router)


def record_startup_event(session_factory: Callable[[], Session]) -> None:
    """Record a startup event using the provided session factory."""

    with session_factory() as session:
        EventsRepository(session).record_event(
            event_type="system_started",
            severity="info",
            component="runtime",
            message="Crypto AI Trader runtime started",
            context={"trade_mode": "paper_auto"},
        )
