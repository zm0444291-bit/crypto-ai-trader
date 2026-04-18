from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from trading.main import app, record_startup_event
from trading.storage.db import Base
from trading.storage.models import Event


def test_health_endpoint_returns_runtime_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["trade_mode"] == "paper_auto"
    assert response.json()["live_trading_enabled"] is False


def test_record_startup_event_writes_system_started():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    record_startup_event(session_factory)

    with session_factory() as session:
        event = session.scalars(select(Event)).one()

    assert event.event_type == "system_started"
    assert event.severity == "info"
    assert event.component == "runtime"
    assert event.context_json == {"trade_mode": "paper_auto"}