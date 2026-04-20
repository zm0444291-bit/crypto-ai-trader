from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import ExecutionRecordsRepository


def test_portfolio_status_rebuilds_paper_account_from_fills(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/portfolio.sqlite3"
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

    response = client.get(
        "/portfolio/status",
        params={"initial_cash_usdt": "500", "BTCUSDT": "110"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cash_balance_usdt"] == "399.9"
    assert body["total_equity_usdt"] == "509.9"
    assert body["unrealized_pnl_usdt"] == "10"
    assert body["positions"][0]["symbol"] == "BTCUSDT"
    assert body["positions"][0]["qty"] == "1"
    assert body["positions"][0]["market_value_usdt"] == "110"


def test_portfolio_status_rejects_negative_initial_cash():
    client = TestClient(app)

    response = client.get(
        "/portfolio/status",
        params={"initial_cash_usdt": "-1"},
    )

    assert response.status_code == 400
    assert "initial_cash_usdt" in response.json()["detail"]


def test_portfolio_status_without_fills_returns_zero_unrealized_pnl():
    client = TestClient(app)

    response = client.get(
        "/portfolio/status",
        params={"initial_cash_usdt": "500"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cash_balance_usdt"] == "500"
    assert body["total_equity_usdt"] == "500"
    assert body["unrealized_pnl_usdt"] == "0"
    assert body["positions"] == []
