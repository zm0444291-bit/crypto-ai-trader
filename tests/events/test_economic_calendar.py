"""Tests for trading.events.economic_calendar."""

from datetime import UTC, datetime

import pytest

from trading.events.economic_calendar import (
    HIGH_IMPACT,
    LOW_IMPACT,
    MEDIUM_IMPACT,
    EconomicCalendar,
    EconomicEvent,
    _parse_fundamental_date,
)


class TestEconomicCalendar:
    @pytest.fixture
    def calendar(self) -> EconomicCalendar:
        return EconomicCalendar()

    def test_is_market_open_true(self, calendar: EconomicCalendar) -> None:
        # Safe hours: Tuesday 10:00 UTC (US session)
        dt = datetime(2025, 6, 3, 10, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is True

    def test_is_market_open_weekend(self, calendar: EconomicCalendar) -> None:
        # Saturday should always be closed
        dt = datetime(2025, 6, 7, 10, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_early_asia(self, calendar: EconomicCalendar) -> None:
        # Sunday 22:00 UTC - just before Asia opens (23:00)
        dt = datetime(2025, 6, 8, 22, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_asia_session(self, calendar: EconomicCalendar) -> None:
        # Monday 01:00 UTC - Asia session active
        dt = datetime(2025, 6, 9, 1, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is True

    def test_is_market_open_late_friday(self, calendar: EconomicCalendar) -> None:
        # Friday 21:00 UTC - just after close (22:00)
        dt = datetime(2025, 6, 6, 21, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_christmas(self, calendar: EconomicCalendar) -> None:
        # Christmas day - markets closed
        dt = datetime(2025, 12, 25, 14, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_new_year(self, calendar: EconomicCalendar) -> None:
        # New Year's Day - markets closed
        dt = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_market_open_good_friday(self, calendar: EconomicCalendar) -> None:
        # Good Friday 2025 - markets closed
        dt = datetime(2025, 4, 18, 14, 0, tzinfo=UTC)
        assert calendar.is_market_open(dt) is False

    def test_is_trading_blocked_no_events(
        self, calendar: EconomicCalendar
    ) -> None:
        dt = datetime(2025, 6, 3, 10, 0, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is False

    def test_is_trading_blocked_non_farm(
        self, calendar: EconomicCalendar
    ) -> None:
        # NFP is HIGH impact - blocks XAUUSD
        dt = datetime(2025, 6, 6, 14, 0, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is True

    def test_is_trading_blocked_farm_no_impact(
        self, calendar: EconomicCalendar
    ) -> None:
        # NFP is HIGH, gold blocked
        dt = datetime(2025, 6, 6, 14, 0, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "EURUSD") is True

    def test_is_trading_blocked_before_event_window(
        self, calendar: EconomicCalendar
    ) -> None:
        # NFP at 14:00 UTC, check at 13:00 UTC (before 30-min window)
        dt = datetime(2025, 6, 6, 13, 0, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is False

    def test_is_trading_blocked_after_event_window(
        self, calendar: EconomicCalendar
    ) -> None:
        # NFP at 14:00 UTC, check at 14:35 UTC (after 30-min window)
        dt = datetime(2025, 6, 6, 14, 35, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is False

    def test_is_trading_blocked_cpi_high(
        self, calendar: EconomicCalendar
    ) -> None:
        # US CPI release - blocks XAUUSD
        dt = datetime(2025, 6, 11, 14, 30, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is True

    def test_is_trading_blocked_fomc_high(
        self, calendar: EconomicCalendar
    ) -> None:
        # FOMC decision at 18:00 UTC - 60-min blackout
        dt = datetime(2025, 6, 18, 18, 30, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is True

    def test_is_trading_blocked_fomc_before(
        self, calendar: EconomicCalendar
    ) -> None:
        # FOMC at 18:00 UTC, check at 17:00 UTC (before 60-min window)
        dt = datetime(2025, 6, 18, 17, 0, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "XAUUSD") is False

    def test_is_trading_blocked_retail_sales_medium_forex(
        self, calendar: EconomicCalendar
    ) -> None:
        # US Retail Sales - MEDIUM impact, blocks EURUSD
        dt = datetime(2025, 6, 17, 14, 30, tzinfo=UTC)
        assert calendar.is_trading_blocked(dt, "EURUSD") is True

    def test_get_impact_level_high(self, calendar: EconomicCalendar) -> None:
        assert calendar.get_impact_level("NFP") == HIGH_IMPACT

    def test_get_impact_level_medium(self, calendar: EconomicCalendar) -> None:
        assert calendar.get_impact_level("Retail Sales") == MEDIUM_IMPACT

    def test_get_impact_level_low(self, calendar: EconomicCalendar) -> None:
        assert calendar.get_impact_level("Housing Starts") == LOW_IMPACT

    def test_get_impact_level_unknown(self, calendar: EconomicCalendar) -> None:
        assert calendar.get_impact_level("Unknown Event") == LOW_IMPACT

    def test_get_next_high_impact_event(
        self, calendar: EconomicCalendar
    ) -> None:
        now = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
        event = calendar.get_next_high_impact_event(now)
        assert event is not None
        assert event.impact == HIGH_IMPACT

    def test_get_next_high_impact_event_none_after_last(
        self, calendar: EconomicCalendar
    ) -> None:
        # Far in the future, beyond all scheduled events
        now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
        event = calendar.get_next_high_impact_event(now)
        assert event is None

    def test_block_symbols_for_event_high_impact(
        self, calendar: EconomicCalendar
    ) -> None:
        event = EconomicEvent(
            name="NFP",
            date=datetime(2025, 6, 6, 14, 0, tzinfo=UTC),
            impact=HIGH_IMPACT,
            affected_symbols=["XAUUSD", "EURUSD"],
        )
        blocked = calendar.block_symbols_for_event(event)
        assert set(blocked) == {"XAUUSD", "EURUSD"}

    def test_block_symbols_for_event_low_impact(
        self, calendar: EconomicCalendar
    ) -> None:
        event = EconomicEvent(
            name="Balance of Trade",
            date=datetime(2025, 6, 6, 14, 0, tzinfo=UTC),
            impact=LOW_IMPACT,
            affected_symbols=["EURUSD"],
        )
        blocked = calendar.block_symbols_for_event(event)
        assert blocked == []

    def test_format_next_event_info(
        self, calendar: EconomicCalendar
    ) -> None:
        now = datetime(2025, 6, 1, 10, 0, tzinfo=UTC)
        info = calendar.format_next_event_info(now)
        assert isinstance(info, str)
        assert "NFP" in info or "CPI" in info or "FOMC" in info


class TestParseFundamentalDate:
    def test_parse_june(self) -> None:
        dt = _parse_fundamental_date("June 6, 2025", "14:00 UTC")
        assert dt is not None
        assert dt.month == 6
        assert dt.day == 6
        assert dt.hour == 14
        assert dt.minute == 0

    def test_parse_january(self) -> None:
        dt = _parse_fundamental_date("Jan 15, 2025", "14:30 UTC")
        assert dt is not None
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 14
        assert dt.minute == 30

    def test_parse_july(self) -> None:
        dt = _parse_fundamental_date("Jul 4, 2025", "18:00 UTC")
        assert dt is not None
        assert dt.month == 7
        assert dt.day == 4
        assert dt.hour == 18
        assert dt.minute == 0

    def test_parse_october(self) -> None:
        dt = _parse_fundamental_date("Oct 30, 2025", "20:00 UTC")
        assert dt is not None
        assert dt.month == 10
        assert dt.day == 30
        assert dt.hour == 20
        assert dt.minute == 0

    def test_parse_december(self) -> None:
        dt = _parse_fundamental_date("Dec 25, 2025", "00:00 UTC")
        assert dt is not None
        assert dt.month == 12
        assert dt.day == 25
