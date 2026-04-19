"""Unit tests for the notification adapters."""

import logging
from unittest.mock import patch

from trading.notifications.base import NotificationContext, NotificationLevel
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

    def test_request_exception_caught_and_logged(self, caplog, monkeypatch):
        import requests

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("Connection refused")

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
        import requests

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        class FakeResponse:
            status_code = 429

            def raise_for_status(self):
                raise requests.HTTPError("429 Too Many Requests")

        with patch("requests.post") as mock_post:
            mock_post.return_value = FakeResponse()

            with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
                notifier.notify(
                    NotificationLevel.WARNING,
                    "Rate limit warning",
                    "Too many requests",
                    None,
                )

            assert "429 Too Many Requests" in caplog.text

    def test_timeout_caught_and_logged(self, caplog, monkeypatch):
        import requests

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")

        notifier = TelegramNotifier()

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.ReadTimeout("Read timed out")

            with caplog.at_level(logging.WARNING, logger="trading.alerts.telegram"):
                notifier.notify(
                    NotificationLevel.ERROR,
                    "Cycle crashed",
                    "Read timeout",
                    None,
                )

            assert "Read timed out" in caplog.text
            assert "Telegram notification failed" in caplog.text
