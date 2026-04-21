"""Unit tests for BreakoutStrategy."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from trading.strategies.active.breakout import BreakoutStrategy


def _ohlcv_df(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    start: datetime | None = None,
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame."""
    if start is None:
        start = datetime(2023, 1, 1, tzinfo=UTC)
    n = len(closes)
    timestamps = [start + timedelta(hours=i) for i in range(n)]
    if highs is None:
        highs = [c + 1.0 for c in closes]
    if lows is None:
        lows = [c - 1.0 for c in closes]
    if volumes is None:
        volumes = [1000.0] * n
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [c - 0.5 for c in closes],
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class TestBreakoutStrategy:
    def test_no_signal_insufficient_data(self):
        s = BreakoutStrategy()
        df = _ohlcv_df([100.0] * 5)
        assert s.generate_signals("BTCUSDT", df) == []

    def test_buy_on_breakout_above_channel_high(self):
        s = BreakoutStrategy()
        # Build a strong uptrend: gradually increasing prices
        # Channel high is max of previous 20 bars; last bar breaks above it
        closes = [100.0 + i * 0.3 for i in range(30)]
        highs = [c + 2.0 for c in closes]
        lows = [c - 2.0 for c in closes]
        # Force last bar to break above channel high
        # Channel high ≈ max of highs[9:29] ≈ 108.7, set last close to 112
        closes[-1] = 112.0
        highs[-1] = 113.0
        lows[-1] = 111.0
        df = _ohlcv_df(closes, highs, lows)
        signals = s.generate_signals("BTCUSDT", df)
        buy_signals = [sig for sig in signals if sig.side == "buy"]
        assert len(buy_signals) == 1
        assert buy_signals[0].side == "buy"

    def test_sell_exit_on_channel_low_break(self):
        s = BreakoutStrategy()
        # Trending market (so regime != range)
        closes = [100.0 + i * 0.5 for i in range(25)]
        highs = [c + 3.0 for c in closes]
        lows = [c - 3.0 for c in closes]
        df = _ohlcv_df(closes, highs, lows)
        # Pre-enter position (simulate by setting flag)
        s._in_position["BTCUSDT"] = True
        # Price falls below channel low on last bar
        # Force last bar's close below channel low
        last_close = 98.0  # well below the ~111.5 channel low
        df.iloc[-1, df.columns.get_loc("close")] = last_close
        df.iloc[-1, df.columns.get_loc("low")] = last_close - 1.0
        signals = s.generate_signals("BTCUSDT", df)
        sell_signals = [sig for sig in signals if sig.side == "sell"]
        assert len(sell_signals) >= 1

    def test_no_entry_in_range_regime(self):
        s = BreakoutStrategy()
        # Flat market (range regime) — ADX will be low
        closes = [100.0] * 50
        highs = [101.0] * 50
        lows = [99.0] * 50
        df = _ohlcv_df(closes, highs, lows)
        s._in_position["BTCUSDT"] = False
        signals = s.generate_signals("BTCUSDT", df)
        buy_signals = [sig for sig in signals if sig.side == "buy"]
        # In range regime, no breakout entries
        assert len(buy_signals) == 0

    def test_strategy_name(self):
        s = BreakoutStrategy()
        assert s.STRATEGY_NAME == "breakout"

    def test_custom_lookback(self):
        s = BreakoutStrategy(lookback=10)
        # With 10-bar lookback, need at least 11 bars
        closes = [100.0 + i * 0.5 for i in range(12)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        df = _ohlcv_df(closes, highs, lows)
        signals = s.generate_signals("BTCUSDT", df)
        # Should not crash regardless of signal
        assert isinstance(signals, list)
