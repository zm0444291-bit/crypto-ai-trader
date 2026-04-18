from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading.market_data.data_quality import (
    DataQualityIssue,
    DataQualityReport,
    check_candle_quality,
    expected_interval_seconds,
)
from trading.market_data.schemas import CandleData


def make_candle(
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    minutes: int = 0,
    close: str = "100",
) -> CandleData:
    """Create a test candle."""
    open_time = datetime(2026, 4, 19, 0, minutes, tzinfo=UTC)
    return CandleData(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("12.5"),
        source="binance",
    )


class TestExpectedIntervalSeconds:
    def test_1m(self):
        assert expected_interval_seconds("1m") == 60

    def test_3m(self):
        assert expected_interval_seconds("3m") == 180

    def test_5m(self):
        assert expected_interval_seconds("5m") == 300

    def test_15m(self):
        assert expected_interval_seconds("15m") == 900

    def test_30m(self):
        assert expected_interval_seconds("30m") == 1800

    def test_1h(self):
        assert expected_interval_seconds("1h") == 3600

    def test_2h(self):
        assert expected_interval_seconds("2h") == 7200

    def test_4h(self):
        assert expected_interval_seconds("4h") == 14400

    def test_6h(self):
        assert expected_interval_seconds("6h") == 21600

    def test_8h(self):
        assert expected_interval_seconds("8h") == 28800

    def test_12h(self):
        assert expected_interval_seconds("12h") == 43200

    def test_1d(self):
        assert expected_interval_seconds("1d") == 86400

    def test_3d(self):
        assert expected_interval_seconds("3d") == 259200


class TestCheckCandleQuality:
    def test_good_15m_candles_returns_ok_true(self):
        now = datetime(2026, 4, 19, 0, 20, tzinfo=UTC)
        candles = [
            make_candle(minutes=0, close="100"),
            make_candle(minutes=15, close="105"),
        ]
        report = check_candle_quality(candles, now)
        assert report.ok is True
        assert report.symbol == "BTCUSDT"
        assert report.timeframe == "15m"
        assert report.issues == []

    def test_empty_list_returns_empty_issue(self):
        now = datetime(2026, 4, 19, 0, 20, tzinfo=UTC)
        report = check_candle_quality([], now)
        assert report.ok is False
        assert any(issue.code == "empty" for issue in report.issues)

    def test_duplicate_open_time_returns_duplicate_issue(self):
        now = datetime(2026, 4, 19, 0, 30, tzinfo=UTC)
        candles = [
            make_candle(minutes=0, close="100"),
            make_candle(minutes=0, close="105"),
        ]
        report = check_candle_quality(candles, now)
        assert report.ok is False
        assert any(issue.code == "duplicate" for issue in report.issues)

    def test_missing_interval_returns_gap_issue(self):
        now = datetime(2026, 4, 19, 0, 45, tzinfo=UTC)
        candles = [
            make_candle(minutes=0, close="100"),
            make_candle(minutes=30, close="105"),
        ]
        report = check_candle_quality(candles, now)
        assert report.ok is False
        assert any(issue.code == "gap" for issue in report.issues)

    def test_stale_candle_returns_stale_issue(self):
        now = datetime(2026, 4, 19, 0, 35, tzinfo=UTC)
        candles = [
            make_candle(minutes=0, close="100"),
        ]
        report = check_candle_quality(candles, now)
        assert report.ok is False
        assert any(issue.code == "stale" for issue in report.issues)

    def test_multiple_issues(self):
        now = datetime(2026, 4, 19, 0, 35, tzinfo=UTC)
        candles = [
            make_candle(minutes=0, close="100"),
            make_candle(minutes=0, close="105"),
        ]
        report = check_candle_quality(candles, now)
        assert report.ok is False
        codes = {issue.code for issue in report.issues}
        assert "duplicate" in codes


class TestDataQualityReport:
    def test_report_is_pydantic_model(self):
        issue = DataQualityIssue(severity="warning", code="gap", message="Gap detected")
        report = DataQualityReport(
            symbol="BTCUSDT",
            timeframe="15m",
            ok=False,
            issues=[issue],
        )
        assert report.ok is False
        assert report.issues[0].code == "gap"


class TestDataQualityIssue:
    def test_issue_is_pydantic_model(self):
        issue = DataQualityIssue(severity="warning", code="gap", message="Gap detected")
        assert issue.severity == "warning"
        assert issue.code == "gap"
        assert issue.message == "Gap detected"
