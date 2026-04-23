"""Economic calendar for tracking high-impact macroeconomic events.

Blocks trading during high-impact events (NFP, CPI, FOMC) for XAUUSD/EURUSD.
Weekend and market holidays are also non-tradeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class ImpactLevel(Enum):
    """Impact level of an economic event."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Public aliases for convenience
HIGH_IMPACT = ImpactLevel.HIGH
MEDIUM_IMPACT = ImpactLevel.MEDIUM
LOW_IMPACT = ImpactLevel.LOW

# Supported currencies for economic events.
SUPPORTED_CURRENCIES: set[str] = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}

# Market holiday dates (UTC, no year - applies annually)
MARKET_HOLIDAYS: set[str] = {
    # Christmas
    "12-25",
    # New Year's Day
    "01-01",
    # Good Friday (placeholder - add specific year)
    "04-18",
}


def _parse_fundamental_date(date_str: str, time_str: str) -> datetime | None:
    """Parse forex-factory style date+time strings into UTC datetime.

    Args:
        date_str: e.g. "June 6, 2025" or "Jan 15, 2025"
        time_str: e.g. "14:00 UTC"

    Returns:
        datetime in UTC, or None if parsing fails.
    """
    try:
        month_map: dict[str, int] = {
            "January": 1,
            "February": 2,
            "March": 3,
            "April": 4,
            "May": 5,
            "June": 6,
            "July": 7,
            "August": 8,
            "September": 9,
            "October": 10,
            "November": 11,
            "December": 12,
            "Jan": 1,
            "Feb": 2,
            "Mar": 3,
            "Apr": 4,
            "Jun": 6,
            "Jul": 7,
            "Aug": 8,
            "Sep": 9,
            "Oct": 10,
            "Nov": 11,
            "Dec": 12,
        }
        # Parse "June 6, 2025" or "Jun 6, 2025"
        parts = date_str.strip().split()
        if len(parts) != 3:
            return None
        month_str, day_str, year_str = parts
        month = month_map.get(month_str.title())
        if month is None:
            return None
        day = int(day_str.rstrip(","))
        year = int(year_str)
        # Parse "14:00 UTC"
        time_parts = time_str.replace("UTC", "").strip().split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)  # noqa: UP017
    except Exception:
        return None


# Pre-defined high-impact event patterns for 2025 (UTC times)
_HIGH_IMPACT_EVENTS_2025: list[tuple[str, str, str, list[str]]] = [
    # (date_str, time_str, event_name, affected_symbols)
    # US Non-Farm Payrolls (NFP) - first Friday of month, 14:00 UTC
    ("June 6, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("July 3, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("Aug 8, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("Sep 5, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("Oct 3, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("Nov 7, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    ("Dec 5, 2025", "14:00 UTC", "NFP", ["XAUUSD", "EURUSD"]),
    # US CPI - typically mid-month, 14:30 UTC
    ("June 11, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("July 10, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("Aug 13, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("Sep 11, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("Oct 10, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("Nov 13, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    ("Dec 10, 2025", "14:30 UTC", "CPI", ["XAUUSD", "EURUSD"]),
    # FOMC Meetings (60-min blackout around decision)
    ("June 18, 2025", "19:00 UTC", "FOMC", ["XAUUSD", "EURUSD"]),
    ("July 30, 2025", "19:00 UTC", "FOMC", ["XAUUSD", "EURUSD"]),
    ("Sep 17, 2025", "19:00 UTC", "FOMC", ["XAUUSD", "EURUSD"]),
    ("Nov 5, 2025", "19:00 UTC", "FOMC", ["XAUUSD", "EURUSD"]),
    ("Dec 17, 2025", "19:00 UTC", "FOMC", ["XAUUSD", "EURUSD"]),
]

# Medium impact events
_MEDIUM_IMPACT_EVENTS_2025: list[tuple[str, str, str, list[str]]] = [
    # US Retail Sales - mid month, 14:30 UTC
    ("June 17, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("July 16, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("Aug 15, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("Sep 16, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("Oct 16, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("Nov 14, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
    ("Dec 16, 2025", "14:30 UTC", "Retail Sales", ["XAUUSD", "EURUSD"]),
]


@dataclass(frozen=True)
class EconomicEvent:
    """A single economic calendar event."""

    name: str
    date: datetime
    impact: ImpactLevel
    affected_symbols: list[str] = field(default_factory=list)
    currency: str = "USD"


class EconomicCalendar:
    """Economic calendar that blocks trading during high-impact events.

    Monitors US macro events (NFP, CPI, FOMC, Retail Sales) and prevents
    trading XAUUSD/EURUSD during high/medium impact windows.
    Also enforces market hours and holiday closures.
    """

    def __init__(self) -> None:
        self._events: list[EconomicEvent] = []
        self._load_2025_events()

    def _load_2025_events(self) -> None:
        """Pre-load 2025 high and medium impact events."""
        for date_str, time_str, event_name, symbols in _HIGH_IMPACT_EVENTS_2025:
            dt = _parse_fundamental_date(date_str, time_str)
            if dt:
                self._events.append(
                    EconomicEvent(
                        name=event_name,
                        date=dt,
                        impact=ImpactLevel.HIGH,
                        affected_symbols=symbols,
                        currency="USD",
                    )
                )
        for date_str, time_str, event_name, symbols in _MEDIUM_IMPACT_EVENTS_2025:
            dt = _parse_fundamental_date(date_str, time_str)
            if dt:
                self._events.append(
                    EconomicEvent(
                        name=event_name,
                        date=dt,
                        impact=ImpactLevel.MEDIUM,
                        affected_symbols=symbols,
                        currency="USD",
                    )
                )

    def is_market_open(self, dt: datetime) -> bool:
        """Check if forex markets are open at the given UTC time.

        Forex market hours (UTC):
        - Sunday 23:00 UTC: Asia opens
        - Friday 22:00 UTC: New York closes

        Args:
            dt: UTC datetime to check.

        Returns:
            True if markets are open, False if closed.
        """
        # Weekend check
        if dt.weekday() >= 5:  # Saturday or Sunday
            # Sunday market opens at 23:00 UTC
            if dt.weekday() == 6 and dt.hour < 23:
                return False
            return False

        # Friday after 21:00 UTC - market closed
        if dt.weekday() == 4 and dt.hour >= 21:
            return False

        # Check market holidays (month-day format)
        month_day = f"{dt.month:02d}-{dt.day:02d}"
        if month_day in MARKET_HOLIDAYS:
            return False

        return True

    def is_trading_blocked(self, dt: datetime, symbol: str) -> bool:
        """Check if trading is blocked for the given symbol at the given time.

        Trading is blocked during:
        - High impact events: 30 minutes before and after
        - Medium impact events: 15 minutes before and after

        Args:
            dt: UTC datetime to check.
            symbol: Trading symbol (e.g. "XAUUSD").

        Returns:
            True if trading is blocked.
        """
        if not self.is_market_open(dt):
            return True

        for event in self._events:
            if event.impact not in (ImpactLevel.HIGH, ImpactLevel.MEDIUM):
                continue
            if symbol not in event.affected_symbols:
                continue

            minutes_before = 30 if event.impact == ImpactLevel.HIGH else 15
            window_start = event.date - timedelta(minutes=minutes_before)
            window_end = event.date + timedelta(minutes=minutes_before)
            if window_start <= dt <= window_end:
                return True

        return False

    def get_impact_level(self, event_name: str) -> ImpactLevel:
        """Return the impact level for a named event.

        Args:
            event_name: Name of the event (e.g. "NFP", "CPI").

        Returns:
            ImpactLevel enum value.
        """
        name_lower = event_name.lower()
        if name_lower in ("nfp", "non-farm payrolls", "fomc", "federal reserve"):
            return ImpactLevel.HIGH
        if name_lower in ("cpi", "consumer price index", "retail sales", "gdp"):
            return ImpactLevel.MEDIUM
        return ImpactLevel.LOW

    def get_next_high_impact_event(
        self, after: datetime
    ) -> EconomicEvent | None:
        """Get the next high-impact event after the given time.

        Args:
            after: UTC datetime threshold.

        Returns:
            Next EconomicEvent with HIGH impact, or None.
        """
        upcoming = sorted(
            [e for e in self._events if e.date > after and e.impact == ImpactLevel.HIGH],
            key=lambda e: e.date,
        )
        return upcoming[0] if upcoming else None

    def block_symbols_for_event(self, event: EconomicEvent) -> list[str]:
        """Return list of symbols blocked by a given event.

        HIGH impact: all affected symbols blocked.
        MEDIUM impact: all affected symbols blocked.
        LOW impact: no symbols blocked.

        Args:
            event: The economic event.

        Returns:
            List of blocked symbol strings.
        """
        if event.impact == ImpactLevel.LOW:
            return []
        return list(event.affected_symbols)

    def format_next_event_info(self, after: datetime) -> str:
        """Get a human-readable string about the next high-impact event.

        Args:
            after: UTC datetime threshold.

        Returns:
            Formatted string with next event details.
        """
        event = self.get_next_high_impact_event(after)
        if event is None:
            return "No upcoming high-impact events."
        return (
            f"Next high-impact event: {event.name} at {event.date.strftime('%Y-%m-%d %H:%M UTC')} "
            f"(blocked symbols: {', '.join(event.affected_symbols)})"
        )
