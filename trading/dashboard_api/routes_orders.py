from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel

from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import ExecutionRecordsRepository

router = APIRouter(tags=["orders"])


class OrderSummary(BaseModel):
    id: int
    mode: str
    exchange: str
    symbol: str
    side: str
    order_type: str
    requested_notional_usdt: Decimal
    status: str
    created_at: datetime


class RecentOrdersResponse(BaseModel):
    orders: list[OrderSummary]


@router.get("/orders/recent", response_model=RecentOrdersResponse)
def read_recent_orders(limit: int = 50) -> RecentOrdersResponse:
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        orders = ExecutionRecordsRepository(session).list_recent_orders(limit=limit)

    return RecentOrdersResponse(
        orders=[
            OrderSummary(
                id=order.id,
                mode=order.mode,
                exchange=order.exchange,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                requested_notional_usdt=order.requested_notional_usdt,
                status=order.status,
                created_at=order.created_at,
            )
            for order in orders
        ]
    )
