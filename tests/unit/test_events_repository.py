from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trading.storage.db import Base
from trading.storage.repositories import EventsRepository


def test_events_repository_records_event():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = EventsRepository(session)
        event = repository.record_event(
            event_type="system_started",
            severity="info",
            component="runtime",
            message="Runtime started",
            context={"trade_mode": "paper_auto"},
        )

        assert event.id is not None
        assert event.event_type == "system_started"
        assert event.severity == "info"
        assert event.context_json == {"trade_mode": "paper_auto"}


def test_events_repository_lists_recent_events_newest_first():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = EventsRepository(session)
        repository.record_event("first", "info", "test", "First event", {})
        repository.record_event("second", "warning", "test", "Second event", {})

        events = repository.list_recent(limit=2)

        assert [event.event_type for event in events] == ["second", "first"]
