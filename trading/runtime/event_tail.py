"""CLI helper for tailing recent runtime events.

Usage:
    python -m trading.runtime.event_tail [--limit N] [--component C] [--severity S] [--event-type T]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import EventsRepository


def _format_time(ts: datetime) -> str:
    """Format a datetime for display, handling tz-naive vs tz-aware."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print recent runtime events from the DB.")
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        metavar="N",
        help="Maximum number of events to print (default: 30)",
    )
    parser.add_argument(
        "--component",
        type=str,
        default=None,
        metavar="C",
        help="Filter by component (exact match)",
    )
    parser.add_argument(
        "--severity",
        type=str,
        default=None,
        metavar="S",
        help="Filter by severity (exact match: info, warning, error, critical)",
    )
    parser.add_argument(
        "--event-type",
        type=str,
        default=None,
        dest="event_type",
        metavar="T",
        help="Filter by event type (exact match)",
    )
    args = parser.parse_args()

    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    factory = create_session_factory(engine)

    header = f"{'TIME':<28} {'SEVERITY':<10} {'COMPONENT':<15} {'TYPE':<35} MESSAGE"
    separator = "-" * 110

    with factory() as session:
        repo = EventsRepository(session)
        events = repo.list_recent(
            limit=args.limit,
            severity=args.severity,
            component=args.component,
            event_type=args.event_type,
        )

        if not events:
            print("No events found matching the given filters.")
            return

        print(header)
        print(separator)
        for e in reversed(events):  # oldest first for readability
            msg = e.message
            if len(msg) > 50:
                msg = msg[:47] + "..."
            created = _format_time(e.created_at)
            print(f"{created:<28} {e.severity:<10} {e.component:<15} {e.event_type:<35} {msg}")


if __name__ == "__main__":
    main()
