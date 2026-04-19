from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import ExecutionRecordsRepository


def test_orders_api_returns_recent_orders(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/orders.sqlite3"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        ExecutionRecordsRepository(session).record_paper_execution(
            PaperOrder(
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                requested_notional_usdt=Decimal("100"),
                status="FILLED",
                created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
            ),
            PaperFill(
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("100"),
                qty=Decimal("1"),
                fee_usdt=Decimal("0.1"),
                slippage_bps=Decimal("0"),
                filled_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
            ),
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    client = TestClient(app)

    response = client.get("/orders/recent")

    assert response.status_code == 200
    body = response.json()
    assert body["orders"][0]["symbol"] == "BTCUSDT"
    assert body["orders"][0]["mode"] == "paper"
    assert body["orders"][0]["status"] == "FILLED"
