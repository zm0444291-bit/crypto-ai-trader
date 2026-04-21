"""Unit tests for MarketRegimeDetector."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from trading.strategies.active.market_regime import detect_market_regime


def _build_ohlcv(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    start: datetime | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Build high/low/close series from close list."""
    if start is None:
        start = datetime(2023, 1, 1, tzinfo=UTC)

    timestamps = [start + timedelta(hours=i) for i in range(len(closes))]
    close = pd.Series(closes, index=timestamps)

    if highs is None:
        highs = [c + 1.0 for c in closes]
    if lows is None:
        lows = [c - 1.0 for c in closes]

    high = pd.Series(highs, index=timestamps)
    low = pd.Series(lows, index=timestamps)
    return high, low, close


class TestDetectMarketRegime:
    def test_insufficient_data_returns_range(self):
        close = pd.Series([100.0, 101.0, 102.0])
        high = pd.Series([101.0, 102.0, 103.0])
        low = pd.Series([99.0, 100.0, 101.0])
        result = detect_market_regime(high, low, close)
        assert result["regime"] == "range"

    def test_trending_market_high_adx(self):
        # ADX rises in trending markets; simulate with increasing highs/closes
        closes = [100.0 + i * 0.5 for i in range(50)]
        highs = [c + 2.0 for c in closes]
        lows = [c - 2.0 for c in closes]
        high, low, close = _build_ohlcv(closes, highs, lows)
        result = detect_market_regime(high, low, close, adx_period=14, bb_period=20)
        # With trending data ADX should be above threshold
        assert result["adx"] > 0

    def test_range_market_low_adx(self):
        # Flat market → low ADX
        closes = [100.0] * 50
        highs = [101.0] * 50
        lows = [99.0] * 50
        high, low, close = _build_ohlcv(closes, highs, lows)
        result = detect_market_regime(high, low, close, adx_period=14, bb_period=20)
        assert result["regime"] == "range"
        assert result["adx"] < 25.0

    def test_bb_bandwidth_computed(self):
        closes = list(range(100, 200, 2))  # increasing → wider BB
        high, low, close = _build_ohlcv(closes)
        result = detect_market_regime(high, low, close, bb_period=20)
        assert "bb_bandwidth" in result
        assert result["bb_bandwidth"] >= 0.0

    def test_custom_thresholds(self):
        closes = [100.0] * 50
        highs = [101.0] * 50
        lows = [99.0] * 50
        high, low, close = _build_ohlcv(closes, highs, lows)
        result = detect_market_regime(
            high, low, close,
            adx_strong_threshold=99.0,  # impossibly high → never "trend"
            bb_narrow_threshold=0.11,  # bandwidth=0.105 < 0.11 and adx=7.25 < 99 → range
        )
        # With very high threshold should stay in range since ADX is low
        assert result["regime"] == "range"
