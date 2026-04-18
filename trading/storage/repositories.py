from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trading.storage.models import Event


class EventsRepository:
    """Persistence helper for runtime events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_type=event_type,
            severity=severity,
            component=component,
            message=message,
            context_json=context or {},
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def list_recent(self, limit: int = 50) -> list[Event]:
        statement = select(Event).order_by(desc(Event.id)).limit(limit)
        return list(self.session.scalars(statement))
