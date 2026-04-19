"""Unit tests for the notification adapters."""

import logging
import time
from unittest.mock import MagicMock, patch

from trading.notifications.base import NotificationContext, NotificationLevel
from trading.notifications.dedup import AlertDeduplicator
from trading.notifications.log_notifier import LogNotifier
from trading.notifications.telegram_notifier import TelegramNotifier


class TestLogNotifier:
    """LogNotifier always succeeds and maps levels to logger calls."""

    def test_info_level_uses_logger_info(self, caplog):
        notifier = LogNotifier()
        with caplog.at_level(logging.INFO, logger="trading.alerts"):
            notifier.notify(
                NotificationLevel.INFO,
                "Test title",
                "Test message",
                NotificationContext(symbol="BTCUSDT"),
            )
        assert "Test title" in caplog.text
        assert "Test message" in caplog.text
        assert "context={'symbol': 'BTCUSDT'}" in caplog.text

    def test_error_level_uses_logger_error(self, caplog):
        notifier = LogNotifier()
        with caplog.at_level(logging.ERROR, logger="trading.alerts"):
            notifier.notify(
                NotificationLevel.ERROR,
                "Cycle crashed",
                "Unexpected exception",
                None,
            )
        assert "Cycle crashed" in caplog.text
        assert "Unexpected exception" in caplog.text

    def test_critical_level_uses_logger_critical(self, caplog):
        notifier = LogNotifier()
        with caplog.at_level(logging.CRITICAL, logger="trading.alerts"):
            notifier.notify(
                NotificationLevel.CRITICAL,
                "Emergency stop",
                "Risk limit breached",
                NotificationContext(risk_state="emergency_stop"),
            )
        assert "Emergency stop" in caplog.text

    def test_no_context_no_crash(self, caplog):
        notifier = LogNotifier()
        with caplog.at_level(logging.INFO, logger="trading.alerts"):
            notifier.notify(NotificationLevel.INFO, "Simple alert", "No context", None)
        assert "Simple alert" in caplog.text


class TestTelegramNotifierMissingConfig:
    """When TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is absent, notify is a no-op."""

    def test_missing_token_noops_silently(self, caplog, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        notifier = TelegramNotifier()
        with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
            notifier.notify(
                NotificationLevel.CRITICAL,
                "Emergency stop",
                "Risk limit breached",
                None,
            )
        # No log, no request, no crash
        assert caplog.text == ""

    def test_missing_chat_id_noops_silently(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        notifier = TelegramNotifier()
        # Should not raise
        notifier.notify(
            NotificationLevel.ERROR,
            "Cycle error",
            "Something broke",
            None,
        )


class TestTelegramNotifierSendFailure:
    """Network errors during send are caught and logged as warnings, not raised."""

    def test_connection_error_caught_and_logged(self, caplog, monkeypatch):
        import httpx

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        with patch("trading.notifications.telegram_notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")

            with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
                notifier.notify(
                    NotificationLevel.ERROR,
                    "Cycle error",
                    "Something broke",
                    NotificationContext(symbol="BTCUSDT", error="Connection refused"),
                )

            assert "Connection refused" in caplog.text
            assert "Telegram notification failed" in caplog.text

    def test_http_error_caught_and_logged(self, caplog, monkeypatch):
        import httpx

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests", request=MagicMock(), response=MagicMock()
        )

        with patch("trading.notifications.telegram_notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_response

            with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
                notifier.notify(
                    NotificationLevel.WARNING,
                    "Rate limit warning",
                    "Too many requests",
                    None,
                )

            assert "429 Too Many Requests" in caplog.text
            assert "Telegram notification HTTP error" in caplog.text

    def test_timeout_caught_and_logged(self, caplog, monkeypatch):
        import httpx

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        with patch("trading.notifications.telegram_notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = httpx.TimeoutException("timed out")

            with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
                notifier.notify(
                    NotificationLevel.ERROR,
                    "Cycle crashed",
                    "Read timeout",
                    None,
                )

            assert "timed out" in caplog.text
            assert "Telegram notification timed out" in caplog.text


class TestAlertDeduplicator:
    """AlertDeduplicator suppresses repeat notifications within a time window."""

    def test_first_notification_is_sent(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok is True

    def test_duplicate_within_window_is_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        ok2 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok1 is True
        assert ok2 is False

    def test_different_symbol_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        ok2 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="ETHUSDT"
        )
        assert ok1 is True
        assert ok2 is True

    def test_different_component_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        ok2 = dedup.should_notify(
            event_type="cycle_error", component="supervisor", symbol="BTCUSDT"
        )
        assert ok1 is True
        assert ok2 is True

    def test_different_event_type_is_not_suppressed(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        ok2 = dedup.should_notify(
            event_type="supervisor_component_error", component="runner", symbol="BTCUSDT"
        )
        assert ok1 is True
        assert ok2 is True

    def test_none_symbol_is_handled(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="heartbeat_lost", component="supervisor", symbol=None
        )
        ok2 = dedup.should_notify(
            event_type="heartbeat_lost", component="supervisor", symbol=None
        )
        assert ok1 is True
        assert ok2 is False

    def test_dedup_resets_after_window_expires(self):
        dedup = AlertDeduplicator(window_seconds=1)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        ok2 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok1 is True
        assert ok2 is False
        time.sleep(1.1)
        ok3 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok3 is True

    def test_reset_for_test_clears_entries(self):
        dedup = AlertDeduplicator(window_seconds=300)
        ok1 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        dedup.reset_for_test()
        ok2 = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok1 is True
        assert ok2 is True

    def test_short_window(self):
        dedup = AlertDeduplicator(window_seconds=60)
        ok = dedup.should_notify(
            event_type="cycle_error", component="runner", symbol="BTCUSDT"
        )
        assert ok is True
