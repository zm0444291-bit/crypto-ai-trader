"""Telegram notifier — sends alerts via a Bot API message.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
If either is missing, the notifier silently no-ops (no crash, no log spam).
Network failures are caught and recorded as warnings without propagating.
"""

import logging
import os
from typing import Any

import httpx

from trading.notifications.base import NotificationContext, NotificationLevel

log = logging.getLogger("trading.alerts.telegram")


class TelegramNotifier:
    """Sends alerts to a Telegram chat via Bot API.

    Falls back to no-op when credentials are absent.
    """

    _BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self) -> None:
        self._token: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id: str | None = os.environ.get("TELEGRAM_CHAT_ID")

    @property
    def _enabled(self) -> bool:
        """True only when both credentials are present."""
        return bool(self._token and self._chat_id)

    def notify(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        context: NotificationContext | None = None,
    ) -> None:
        if not self._enabled:
            log.debug("Telegram notifier disabled (token or chat_id missing)")
            return

        body = self._format_message(level, title, message, context)
        self._send(body)

    def _format_message(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        context: NotificationContext | None,
    ) -> str:
        icon = {
            NotificationLevel.INFO: "ℹ️",
            NotificationLevel.WARNING: "⚠️",
            NotificationLevel.ERROR: "❗",
            NotificationLevel.CRITICAL: "🚨",
        }.get(level, "ℹ️")

        lines = [f"{icon} *{title}*", message]
        if context:
            parts = [f"{k}={v}" for k, v in context.items()]
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def _send(self, text: str) -> None:
        try:
            token = self._token
            url = self._BASE_URL.format(token=token)
            payload: dict[str, Any] = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            with httpx.Client(timeout=httpx.Timeout(5, read=10)) as client:
                resp = client.post(url, data=payload)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            log.error("Telegram notification timed out: %s", exc)
        except httpx.HTTPStatusError as exc:
            log.error("Telegram notification HTTP error: %s", exc)
        except httpx.HTTPError as exc:
            log.error("Telegram notification failed: %s", exc)
