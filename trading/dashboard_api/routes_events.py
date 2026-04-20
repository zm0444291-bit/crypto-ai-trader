from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import EventsRepository

router = APIRouter(tags=["events"])


class EventSummary(BaseModel):
    id: int
    event_type: str
    severity: str
    component: str
    message: str
    context: dict[str, Any]
    created_at: datetime
    trace_id: str | None = None
    cycle_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    mode: str | None = None
    lifecycle_stage: str | None = None
    reason: str | None = None


class RecentEventsResponse(BaseModel):
    events: list[EventSummary]


class LifecycleChainResponse(BaseModel):
    events: list[EventSummary]
    count: int


@router.get("/events/recent", response_model=RecentEventsResponse)
def read_recent_events(
    limit: int = 50,
    severity: str | None = None,
    component: str | None = None,
    event_type: str | None = None,
    lifecycle_stage: str | None = None,
) -> RecentEventsResponse:
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        events = repo.list_recent(
            limit=limit,
            severity=severity,
            component=component,
            event_type=event_type,
            lifecycle_stage=lifecycle_stage,
        )

    return RecentEventsResponse(
        events=[
            EventSummary(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                component=event.component,
                message=event.message,
                context=event.context_json,
                created_at=event.created_at,
                trace_id=event.trace_id,
                cycle_id=event.cycle_id,
                symbol=event.symbol,
                side=event.side,
                mode=event.mode,
                lifecycle_stage=event.lifecycle_stage,
                reason=event.reason,
            )
            for event in events
        ]
    )


@router.get("/events/lifecycle/trace/{trace_id}", response_model=LifecycleChainResponse)
def read_events_by_trace(
    trace_id: str,
    limit: int = 100,
) -> LifecycleChainResponse:
    """Return the full lifecycle chain for a trace_id, ordered chronologically."""
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        events = repo.list_by_trace_id(trace_id, limit=limit)

    return LifecycleChainResponse(
        events=[
            EventSummary(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                component=event.component,
                message=event.message,
                context=event.context_json,
                created_at=event.created_at,
                trace_id=event.trace_id,
                cycle_id=event.cycle_id,
                symbol=event.symbol,
                side=event.side,
                mode=event.mode,
                lifecycle_stage=event.lifecycle_stage,
                reason=event.reason,
            )
            for event in events
        ],
        count=len(events),
    )


@router.get("/events/lifecycle/cycle/{cycle_id}", response_model=LifecycleChainResponse)
def read_events_by_cycle(
    cycle_id: str,
    limit: int = 50,
) -> LifecycleChainResponse:
    """Return all events for a cycle_id, ordered chronologically."""
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = EventsRepository(session)
        events = repo.list_by_cycle_id(cycle_id, limit=limit)

    return LifecycleChainResponse(
        events=[
            EventSummary(
                id=event.id,
                event_type=event.event_type,
                severity=event.severity,
                component=event.component,
                message=event.message,
                context=event.context_json,
                created_at=event.created_at,
                trace_id=event.trace_id,
                cycle_id=event.cycle_id,
                symbol=event.symbol,
                side=event.side,
                mode=event.mode,
                lifecycle_stage=event.lifecycle_stage,
                reason=event.reason,
            )
            for event in events
        ],
        count=len(events),
    )
