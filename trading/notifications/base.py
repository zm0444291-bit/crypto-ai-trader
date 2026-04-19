"""Notification interface for runtime alerts."""

from enum import Enum
from typing import Protocol

from typing_extensions import TypedDict


class NotificationLevel(Enum):
    """Alert severity level."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationContext(TypedDict, total=False):
    """Extra context attached to a notification."""

    # Identification
    event_type: str
    component: str
    symbol: str
    # State at time of alert
    mode: str
    risk_state: str
    guard_reason: str
    # Metrics
    cycles_last_hour: int
    orders_last_hour: int
    cycle: int
    # Error detail (used when event_type / component are insufficient alone)
    error: str


class Notifier(Protocol):
    """Protocol for runtime alert notifiers.

    Implement this interface for any notification backend
    (log, Telegram, email, push, etc.).
    """

    def notify(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        context: NotificationContext | None = None,
    ) -> None:
        """Send a notification.

        Args:
            level: Alert severity (INFO / WARNING / ERROR / CRITICAL).
            title: Short one-line alert title.
            message: Human-readable alert body.
            context: Optional structured metadata.
        """
        ...
