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


class RecentEventsResponse(BaseModel):
    events: list[EventSummary]


@router.get("/events/recent", response_model=RecentEventsResponse)
def read_recent_events(
    limit: int = 50,
    severity: str | None = None,
    component: str | None = None,
    event_type: str | None = None,
) -> RecentEventsResponse:
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        events = EventsRepository(session).list_recent(
            limit=limit,
            severity=severity,
            component=component,
            event_type=event_type,
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
            )
            for event in events
        ]
    )
