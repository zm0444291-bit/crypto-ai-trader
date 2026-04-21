from datetime import UTC, datetime, timedelta
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


class OrderLifecycleSummaryResponse(BaseModel):
    window_hours: int
    total_orders: int
    pending_unknown_count: int
    failed_count: int
    rejected_count: int
    status_counts: dict[str, int]
    latest_order_time: datetime | None


def _as_aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


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


@router.get("/orders/lifecycle/summary", response_model=OrderLifecycleSummaryResponse)
def read_order_lifecycle_summary(
    window_hours: int = 24,
    limit: int = 500,
) -> OrderLifecycleSummaryResponse:
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=window_hours)

    with session_factory() as session:
        orders = ExecutionRecordsRepository(session).list_recent_orders(limit=limit)

    status_counts: dict[str, int] = {}
    pending_unknown_count = 0
    failed_count = 0
    rejected_count = 0
    latest_order_time: datetime | None = None
    total_orders = 0

    for order in orders:
        created = _as_aware_utc(order.created_at)
        if created < cutoff:
            continue

        total_orders += 1
        latest_order_time = (
            created
            if latest_order_time is None
            else max(latest_order_time, created)
        )

        status = str(order.status).upper()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "PENDING_UNKNOWN":
            pending_unknown_count += 1
        if status == "FAILED":
            failed_count += 1
        if status == "REJECTED":
            rejected_count += 1

    return OrderLifecycleSummaryResponse(
        window_hours=window_hours,
        total_orders=total_orders,
        pending_unknown_count=pending_unknown_count,
        failed_count=failed_count,
        rejected_count=rejected_count,
        status_counts=status_counts,
        latest_order_time=latest_order_time,
    )
