"""Tests for trading/runtime/runner.py — APIFailureDegradation."""

from datetime import UTC, datetime, timedelta

from trading.runtime.runner import APIFailureDegradation


class TestAPIFailureDegradationMarketData:
    """VA-0.2.1 / VA-0.2.2 / VA-0.2.5"""

    def test_third_failure_freezes_symbol(self):
        deg = APIFailureDegradation(
            market_data_freeze_threshold=3,
            market_data_freeze_minutes=30,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        # 1st — retry
        assert deg.handle_market_data_failure(symbol, now=now) == "retry"
        assert not deg.is_symbol_frozen(symbol, now=now)

        # 2nd — retry
        assert deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=1)) == "retry"
        assert not deg.is_symbol_frozen(symbol, now=now + timedelta(seconds=1))

        # 3rd — frozen
        assert deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=2)) == "frozen"
        assert deg.is_symbol_frozen(symbol, now=now + timedelta(seconds=2))

    def test_freeze_expires_after_30_minutes(self):
        deg = APIFailureDegradation(
            market_data_freeze_threshold=3,
            market_data_freeze_minutes=30,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_market_data_failure(symbol, now=now)
        deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=1))
        deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=2))  # frozen

        # Still frozen at 29 min
        still_frozen = now + timedelta(minutes=29) + timedelta(seconds=2)
        assert deg.is_symbol_frozen(symbol, now=still_frozen)

        # Unfrozen at 30 min 1 sec
        unfrozen_at = now + timedelta(minutes=30) + timedelta(seconds=3)
        assert not deg.is_symbol_frozen(symbol, now=unfrozen_at)

    def test_frozen_symbol_skipped(self):
        deg = APIFailureDegradation(
            market_data_freeze_threshold=3,
            market_data_freeze_minutes=30,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_market_data_failure(symbol, now=now)
        deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=1))
        deg.handle_market_data_failure(symbol, now=now + timedelta(seconds=2))

        # Frozen symbol reports frozen
        assert deg.is_symbol_frozen(symbol, now=now + timedelta(seconds=2))
        # Other symbols are not affected
        assert not deg.is_symbol_frozen("ETHUSDT", now=now + timedelta(seconds=2))


class TestAPIFailureDegradationOrder:
    """VA-0.2.3 / VA-0.2.5"""

    def test_rate_limit_returns_retry_without_counting(self):
        deg = APIFailureDegradation(
            order_failure_freeze_threshold=3,
            order_failure_freeze_minutes=60,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        for _ in range(5):
            result = deg.handle_order_failure(symbol, is_rate_limited=True, now=now)
            assert result == "retry"

        # Counter should still be 0 — rate-limited never counted
        assert deg._order_failures.get(symbol, 0) == 0
        assert not deg.is_symbol_frozen(symbol, now=now)

    def test_third_non_rate_limit_failure_freezes_and_returns_abort(self):
        deg = APIFailureDegradation(
            order_failure_freeze_threshold=3,
            order_failure_freeze_minutes=60,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        # 1st non-rate-limit — retry_counted
        r1 = deg.handle_order_failure(symbol, is_rate_limited=False, now=now)
        assert r1 == "retry_counted"

        # 2nd non-rate-limit — retry_counted
        r2 = deg.handle_order_failure(
            symbol, is_rate_limited=False, now=now + timedelta(seconds=1)
        )
        assert r2 == "retry_counted"

        # 3rd non-rate-limit — frozen
        r3 = deg.handle_order_failure(
            symbol, is_rate_limited=False, now=now + timedelta(seconds=2)
        )
        assert r3 == "frozen"
        assert deg.is_symbol_frozen(symbol, now=now + timedelta(seconds=2))

    def test_order_freeze_expires_after_60_minutes(self):
        deg = APIFailureDegradation(
            order_failure_freeze_threshold=3,
            order_failure_freeze_minutes=60,
        )
        symbol = "BTCUSDT"
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_order_failure(symbol, is_rate_limited=False, now=now)
        deg.handle_order_failure(symbol, is_rate_limited=False, now=now + timedelta(seconds=1))
        deg.handle_order_failure(
            symbol, is_rate_limited=False, now=now + timedelta(seconds=2)
        )  # frozen

        # Still frozen at 59 min
        assert deg.is_symbol_frozen(symbol, now=now + timedelta(minutes=59) + timedelta(seconds=2))

        # Unfrozen at 60 min 1 sec
        assert not deg.is_symbol_frozen(symbol, now=now + timedelta(minutes=60) + timedelta(seconds=3))


class TestAPIFailureDegradationPerSymbol:
    """VA-0.2.5"""

    def test_market_data_freeze_is_per_symbol(self):
        deg = APIFailureDegradation(market_data_freeze_threshold=3, market_data_freeze_minutes=30)
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        for _ in range(3):
            deg.handle_market_data_failure("BTCUSDT", now=now)
            now += timedelta(seconds=1)

        assert deg.is_symbol_frozen("BTCUSDT", now=now)
        assert not deg.is_symbol_frozen("ETHUSDT", now=now)  # different symbol, not frozen

    def test_order_freeze_is_per_symbol(self):
        deg = APIFailureDegradation(order_failure_freeze_threshold=3, order_failure_freeze_minutes=60)
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        for _ in range(3):
            deg.handle_order_failure("BTCUSDT", is_rate_limited=False, now=now)
            now += timedelta(seconds=1)

        assert deg.is_symbol_frozen("BTCUSDT", now=now)
        assert not deg.is_symbol_frozen("ETHUSDT", now=now)  # different symbol, not frozen


class TestAPIFailureDegradationTelegramAlert:
    """VA-0.2.4 — Telegram notifier called on freeze."""

    def test_freeze_sends_telegram_alert(self):
        class SpyTelegramNotifier:
            calls: list[dict]

            def __init__(self) -> None:
                self.calls = []

            def notify(
                self, level: object, title: str, message: str, context: object
            ) -> None:
                self.calls.append(
                    {"level": level, "title": title, "message": message, "context": context}
                )

        spy = SpyTelegramNotifier()
        deg = APIFailureDegradation(
            market_data_freeze_threshold=2,
            market_data_freeze_minutes=30,
            telegram_notifier=spy,
        )
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_market_data_failure("BTCUSDT", now=now)  # 1st
        deg.handle_market_data_failure("BTCUSDT", now=now + timedelta(seconds=1))  # 2nd → freeze

        assert len(spy.calls) == 1
        assert "BTCUSDT" in spy.calls[0]["title"]
        assert "market-data" in spy.calls[0]["title"]

    def test_no_telegram_when_notifier_is_none(self):
        deg = APIFailureDegradation(
            market_data_freeze_threshold=2,
            market_data_freeze_minutes=30,
            telegram_notifier=None,
        )
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        # Should not raise even with no notifier
        deg.handle_market_data_failure("BTCUSDT", now=now)
        deg.handle_market_data_failure("BTCUSDT", now=now + timedelta(seconds=1))

        assert deg.is_symbol_frozen("BTCUSDT", now=now + timedelta(seconds=1))


class TestFrozenMinutesRemaining:
    """Helper methods for freeze time remaining."""

    def test_market_data_minutes_remaining(self):
        deg = APIFailureDegradation(market_data_freeze_threshold=2, market_data_freeze_minutes=30)
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_market_data_failure("BTCUSDT", now=now)
        deg.handle_market_data_failure("BTCUSDT", now=now + timedelta(seconds=1))

        remaining = deg.market_data_frozen_minutes_remaining("BTCUSDT", now=now + timedelta(seconds=2))
        # Freeze set at 12:00:01, microseconds zeroed to 12:00:01, expires at 12:30:01.
        # At 12:00:02 -> (12:30:01 - 12:00:02).seconds = 29 min 59 sec = 1799 s
        assert remaining == 1799

    def test_market_data_minutes_remaining_not_frozen(self):
        deg = APIFailureDegradation(market_data_freeze_threshold=3, market_data_freeze_minutes=30)
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        assert deg.market_data_frozen_minutes_remaining("BTCUSDT", now=now) == 0

    def test_order_minutes_remaining(self):
        deg = APIFailureDegradation(order_failure_freeze_threshold=2, order_failure_freeze_minutes=60)
        now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        deg.handle_order_failure("BTCUSDT", is_rate_limited=False, now=now)
        deg.handle_order_failure("BTCUSDT", is_rate_limited=False, now=now + timedelta(seconds=1))

        remaining = deg.order_frozen_minutes_remaining("BTCUSDT", now=now + timedelta(seconds=2))
        # Freeze set at 12:00:01, microseconds zeroed to 12:00:01, expires at 13:00:01.
        # At 12:00:02 -> (13:00:01 - 12:00:02).seconds = 59 min 59 sec = 3599 s
        assert remaining == 3599
