from datetime import datetime

from pydantic import BaseModel

from trading.market_data.schemas import CandleData


class DataQualityIssue(BaseModel):
    severity: str
    code: str
    message: str


class DataQualityReport(BaseModel):
    symbol: str
    timeframe: str
    ok: bool
    issues: list[DataQualityIssue]


def expected_interval_seconds(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    multipliers = {"m": 60, "h": 3600, "d": 86400}
    if unit not in multipliers:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return value * multipliers[unit]


def check_candle_quality(candles: list[CandleData], now: datetime) -> DataQualityReport:
    if not candles:
        return DataQualityReport(
            symbol="",
            timeframe="",
            ok=False,
            issues=[
                DataQualityIssue(
                    severity="error",
                    code="empty",
                    message="No candles available.",
                )
            ],
        )

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    issues: list[DataQualityIssue] = []
    interval_seconds = expected_interval_seconds(ordered[0].timeframe)

    seen_open_times = set()
    for candle in ordered:
        if candle.open_time in seen_open_times:
            issues.append(
                DataQualityIssue(
                    severity="error",
                    code="duplicate",
                    message=f"Duplicate candle open_time: {candle.open_time.isoformat()}",
                )
            )
        seen_open_times.add(candle.open_time)

    for previous, current in zip(ordered, ordered[1:], strict=False):
        delta_seconds = (current.open_time - previous.open_time).total_seconds()
        if delta_seconds > interval_seconds:
            issues.append(
                DataQualityIssue(
                    severity="warning",
                    code="gap",
                    message="Candle gap detected.",
                )
            )

    latest_age_seconds = (now - ordered[-1].open_time).total_seconds()
    if latest_age_seconds > interval_seconds * 2:
        issues.append(
            DataQualityIssue(
                severity="warning",
                code="stale",
                message="Latest closed candle is stale.",
            )
        )

    return DataQualityReport(
        symbol=ordered[0].symbol,
        timeframe=ordered[0].timeframe,
        ok=not issues,
        issues=issues,
    )
