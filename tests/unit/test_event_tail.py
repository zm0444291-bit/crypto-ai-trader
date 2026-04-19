"""Unit tests for trading.runtime.event_tail helper."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trading.storage.db import Base
from trading.storage.repositories import EventsRepository


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC)


def test_format_time_aware():
    """Verify that a tz-aware datetime is returned unchanged."""
    from trading.runtime.event_tail import _format_time

    ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = _format_time(ts)
    assert "2025-01-01" in result


def test_format_time_naive_becomes_aware():
    """Verify that a tz-naive datetime is localised to UTC."""
    from trading.runtime.event_tail import _format_time

    ts = datetime(2025, 1, 1, 12, 0, 0)
    result = _format_time(ts)
    assert "2025-01-01" in result
    assert "+00:00" in result


def test_list_recent_filtered_by_severity():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        repo.record_event("type_a", "error", "test", "Error msg", {})
        repo.record_event("type_b", "info", "test", "Info msg", {})
        repo.record_event("type_c", "warning", "test", "Warn msg", {})

        errors = repo.list_recent(limit=10, severity="error")
        assert len(errors) == 1
        assert errors[0].severity == "error"


def test_list_recent_filtered_by_component():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        repo.record_event("type_a", "info", "component_a", "Msg A", {})
        repo.record_event("type_b", "info", "component_b", "Msg B", {})

        component_a = repo.list_recent(limit=10, component="component_a")
        assert len(component_a) == 1
        assert component_a[0].component == "component_a"


def test_list_recent_filtered_by_event_type():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        repo.record_event("heartbeat", "info", "supervisor", "HB", {})
        repo.record_event("cycle_error", "error", "trader", "Err", {})

        heartbeats = repo.list_recent(limit=10, event_type="heartbeat")
        assert len(heartbeats) == 1
        assert heartbeats[0].event_type == "heartbeat"


def test_list_recent_respects_limit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        for i in range(10):
            repo.record_event(f"type_{i}", "info", "test", f"Msg {i}", {})

        events = repo.list_recent(limit=3)
        assert len(events) == 3
