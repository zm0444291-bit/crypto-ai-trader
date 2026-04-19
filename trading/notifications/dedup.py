"""Alert deduplication — throttles repeat notifications within a time window.

Events are ALWAYS recorded to the DB (audit completeness). Only the
notification delivery is throttled.

Deduplication key: (event_type, component, symbol) — the combination
that makes an alert truly "the same".

Default window: 5 minutes.同类错误在窗口期内只推送一次通知。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock


@dataclass(frozen=True)
class DedupKey:
    event_type: str
    component: str
    symbol: str | None


@dataclass
class DedupEntry:
    key: DedupKey
    expire_at: datetime


class AlertDeduplicator:
    """Thread-safe deduplicator for runtime alert notifications.

    Tracks recently sent notifications and suppresses duplicates within
    a configurable time window. DB events are never suppressed.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._entries: dict[DedupKey, DedupEntry] = {}
        self._lock = Lock()

    def should_notify(self, event_type: str, component: str, symbol: str | None) -> bool:
        """Return True if notification should be sent; False if it is a duplicate.

        When False is returned the caller should skip notification delivery
        (but MUST still record the event to the DB).
        """
        key = DedupKey(event_type=event_type, component=component, symbol=symbol or None)
        now = datetime.now(UTC)

        with self._lock:
            # Evict expired entries first to keep the dict bounded
            expired = [k for k, v in self._entries.items() if v.expire_at <= now]
            for k in expired:
                del self._entries[k]

            if key in self._entries:
                return False  # still within deduplication window

            self._entries[key] = DedupEntry(
                key=key,
                expire_at=now + self._window,
            )
            return True

    def should_notify_with_key(self, key: DedupKey) -> bool:
        """Variant that accepts a pre-built DedupKey (avoids re-computing symbol)."""
        now = datetime.now(UTC)
        with self._lock:
            expired = [k for k, v in self._entries.items() if v.expire_at <= now]
            for k in expired:
                del self._entries[k]

            if key in self._entries:
                return False
            self._entries[key] = DedupEntry(key=key, expire_at=now + self._window)
            return True

    def reset_for_test(self) -> None:
        """Clear all entries — use only in tests."""
        with self._lock:
            self._entries.clear()
