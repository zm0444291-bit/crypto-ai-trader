import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from trading.dashboard_api.routes_analytics import router as analytics_router
from trading.dashboard_api.routes_events import router as events_router
from trading.dashboard_api.routes_health import router as health_router
from trading.dashboard_api.routes_market_data import router as market_data_router
from trading.dashboard_api.routes_orders import router as orders_router
from trading.dashboard_api.routes_portfolio import router as portfolio_router
from trading.dashboard_api.routes_risk import router as risk_router
from trading.dashboard_api.routes_runtime import router as runtime_router
from trading.dashboard_api.ws_manager import get_manager, register_loop
from trading.dashboard_api.ws_manager import router as ws_router
from trading.market_data.market_data_ws_manager import get_market_data_manager
from trading.storage.repositories import EventsRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop WS managers when FastAPI server starts/shuts down."""
    register_loop(asyncio.get_running_loop())

    # Dashboard WS manager (runtime events → browser)
    manager = get_manager()
    manager.start()

    # Binance market data WS → dashboard WS bridge
    md_manager = get_market_data_manager()
    await md_manager.start()

    yield

    await md_manager.stop()
    await manager.stop()


app = FastAPI(title="Crypto AI Trader", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(ws_router)
app.include_router(analytics_router)
app.include_router(events_router)
app.include_router(health_router)
app.include_router(market_data_router)
app.include_router(orders_router)
app.include_router(portfolio_router)
app.include_router(risk_router)
app.include_router(runtime_router)


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
