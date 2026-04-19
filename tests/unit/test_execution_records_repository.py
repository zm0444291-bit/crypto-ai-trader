from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.storage.db import Base
from trading.storage.repositories import ExecutionRecordsRepository


def make_order() -> PaperOrder:
    return PaperOrder(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        requested_notional_usdt=Decimal("100"),
        status="FILLED",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def make_fill() -> PaperFill:
    return PaperFill(
        symbol="BTCUSDT",
        side="BUY",
        price=Decimal("100.2"),
        qty=Decimal("0.9970059880239520958083832335"),
        fee_usdt=Decimal("0.1"),
        slippage_bps=Decimal("20"),
        filled_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def test_execution_records_repository_records_order_and_fill():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = ExecutionRecordsRepository(session)

        order, fill = repository.record_paper_execution(make_order(), make_fill())

        assert order.id is not None
        assert fill.id is not None
        assert fill.order_id == order.id
        assert order.mode == "paper"
        assert order.exchange == "paper"
        assert order.symbol == "BTCUSDT"
        assert fill.price == Decimal("100.2000000000")


def test_execution_records_repository_lists_recent_orders_newest_first():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = ExecutionRecordsRepository(session)
        repository.record_paper_execution(make_order(), make_fill())
        second_order = make_order().model_copy(
            update={"created_at": datetime(2026, 4, 19, 1, 5, tzinfo=UTC)}
        )
        second_fill = make_fill().model_copy(
            update={"filled_at": datetime(2026, 4, 19, 1, 5, tzinfo=UTC)}
        )
        repository.record_paper_execution(second_order, second_fill)

        orders = repository.list_recent_orders(limit=2)

        assert [order.created_at.minute for order in orders] == [5, 0]
