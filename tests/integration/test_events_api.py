from fastapi.testclient import TestClient

from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import EventsRepository


def test_events_api_returns_recent_events_newest_first(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/events.sqlite3"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repository = EventsRepository(session)
        repository.record_event(
            event_type="system_started",
            severity="info",
            component="runtime",
            message="System started",
            context={"mode": "paper_auto"},
        )
        repository.record_event(
            event_type="risk_state_changed",
            severity="warning",
            component="risk",
            message="Daily loss reached degraded state",
            context={"risk_state": "degraded"},
        )

    monkeypatch.setenv("DATABASE_URL", database_url)
    client = TestClient(app)

    response = client.get("/events/recent", params={"limit": "10"})

    assert response.status_code == 200
    body = response.json()
    assert [event["event_type"] for event in body["events"]] == [
        "risk_state_changed",
        "system_started",
    ]
    assert body["events"][0]["component"] == "risk"
    assert body["events"][0]["context"] == {"risk_state": "degraded"}
