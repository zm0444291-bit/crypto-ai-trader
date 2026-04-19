"""Unit tests for the AlertDeduplicator."""

import time
from datetime import UTC, datetime, timedelta

from trading.notifications.dedup import AlertDeduplicator, DedupKey


class TestAlertDeduplicator:
    """AlertDeduplicator suppresses repeat notifications within a time window."""

    def _clock(self, dedup: AlertDeduplicator, seconds_offset: int = 0) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=seconds_offset)

    # ── first notification always allowed ─────────────────────────────────────

    def test_first_notification_is_allowed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        assert (
            dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
            is True
        )

    # ── same key within window is suppressed ───────────────────────────────────

    def test_same_key_within_window_is_blocked(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        # Second call within window
        assert (
            dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
            is False
        )

    def test_different_symbol_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        assert (
            dedup.should_notify(event_type="cycle_error", component="runner", symbol="ETHUSDT")
            is True
        )

    def test_different_component_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        assert (
            dedup.should_notify(event_type="cycle_error", component="paper_cycle", symbol="BTCUSDT")
            is True
        )

    def test_different_event_type_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        assert (
            dedup.should_notify(event_type="cycle_started", component="runner", symbol="BTCUSDT")
            is True
        )

    # ── same key after window expires is allowed again ───────────────────────────

    def test_same_key_after_window_expires_is_allowed(self):
        dedup = AlertDeduplicator(window_seconds=1)  # 1-second window
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        time.sleep(1.1)
        assert (
            dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
            is True
        )

    # ── None symbol treated as None ────────────────────────────────────────────

    def test_none_symbol_same_as_absent(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="heartbeat_lost", component="supervisor", symbol=None)
        # Should be suppressed
        assert (
            dedup.should_notify(event_type="heartbeat_lost", component="supervisor", symbol=None)
            is False
        )
        # Explicit None passed again — same key
        assert (
            dedup.should_notify(event_type="heartbeat_lost", component="supervisor", symbol=None)
            is False
        )

    # ── should_notify_with_key variant ──────────────────────────────────────────

    def test_should_notify_with_key_same_key_blocked(self):
        dedup = AlertDeduplicator(window_seconds=300)
        key = DedupKey(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        assert dedup.should_notify_with_key(key) is True
        assert dedup.should_notify_with_key(key) is False

    def test_should_notify_with_key_different_key_allowed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        key1 = DedupKey(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        key2 = DedupKey(event_type="cycle_error", component="runner", symbol="ETHUSDT")
        assert dedup.should_notify_with_key(key1) is True
        assert dedup.should_notify_with_key(key2) is True

    # ── reset_for_test ─────────────────────────────────────────────────────────

    def test_reset_clears_all_entries(self):
        dedup = AlertDeduplicator(window_seconds=300)
        dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
        dedup.should_notify(event_type="cycle_error", component="paper_cycle", symbol="BTCUSDT")
        dedup.reset_for_test()
        # After reset, all keys should be allowed again
        assert (
            dedup.should_notify(event_type="cycle_error", component="runner", symbol="BTCUSDT")
            is True
        )
        assert (
            dedup.should_notify(event_type="cycle_error", component="paper_cycle", symbol="BTCUSDT")
            is True
        )

    # ── concurrent access ──────────────────────────────────────────────────────

    def test_concurrent_notifications_all_handled(self):
        """Multiple threads calling should_notify simultaneously do not raise."""
        import threading

        dedup = AlertDeduplicator(window_seconds=300)
        results: list[bool] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def notify_once():
            try:
                barrier.wait()  # synchronize threads so they call at the same time
                result = dedup.should_notify(
                    event_type="cycle_error", component="runner", symbol="BTCUSDT"
                )
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=notify_once) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Exactly 1 True (first call), rest are False — regardless of thread timing
        assert results.count(True) == 1
        assert results.count(False) == 9
