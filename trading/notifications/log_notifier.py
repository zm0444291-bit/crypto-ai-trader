"""Log-only notifier — writes structured entries to the Python logger."""

import logging

from trading.notifications.base import NotificationContext, NotificationLevel

logger = logging.getLogger("trading.alerts")


class LogNotifier:
    """Notifies via Python stdlib logging.

    Always available, never fails. Logs at a level derived from the alert level:
    - INFO    -> logger.info
    - WARNING -> logger.warning
    - ERROR   -> logger.error
    - CRITICAL -> logger.critical
    """

    def notify(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        context: NotificationContext | None = None,
    ) -> None:
        context_str = f" | context={context}" if context else ""
        full = f"[{level.value.upper()}] {title} — {message}{context_str}"

        match level:
            case NotificationLevel.INFO:
                logger.info("%s", full)
            case NotificationLevel.WARNING:
                logger.warning("%s", full)
            case NotificationLevel.ERROR:
                logger.error("%s", full)
            case NotificationLevel.CRITICAL:
                logger.critical("%s", full)
            case _:
                logger.info("%s", full)
