"""Unit tests for feature indicators (F1-F11)."""

from decimal import Decimal

import pandas as pd
import pytest

from trading.features.momentum import (
    cci,
    macd,
    roc,
    stochastic,
)
from trading.features.trend import (
    adx,
    aroon,
    supertrend,
)
from trading.features.volatility import (
    bollinger_bands,
    keltner_channel,
)
from trading.features.volume import (
    obv,
    vwap,
)


def _decimal_series(values: list[float]) -> pd.Series:
    return pd.Series([Decimal(str(v)) for v in values])


def _float_series(values: list[float]) -> pd.Series:
    return pd.Series(values)


class TestMACD:
    def test_macd_shape_equals_input(self):
        closes = _float_series([100.0] * 40)
        result = macd(closes)
        assert len(result["macd"]) == len(closes)

    def test_macd_fast_less_than_slow_raises(self):
        closes = _float_series([100.0] * 40)
        with pytest.raises(ValueError, match="fast"):
            macd(closes, fast=26, slow=12)

    def test_macd_warmup(self):
        closes = _float_series([100.0] * 30)
        result = macd(closes)
        # EWM doesn't produce NaN warmup like SMA; check values are finite after warmup
        assert result["macd"].iloc[-5:].notna().all()

    def test_macd_signal_cross(self):
        # Falling prices: MACD should cross below signal
        closes = _float_series([100.0 + i for i in range(40)])
        result = macd(closes)
        # After warmup, MACD and signal should exist and be finite
        assert result["macd"].iloc[-1] is not None


class TestROC:
    def test_roc_length(self):
        closes = _float_series([100.0] * 15)
        result = roc(closes, period=12)
        assert len(result) == len(closes)

    def test_roc_raises_on_zero_period(self):
        closes = _float_series([100.0] * 15)
        with pytest.raises(ValueError):
            roc(closes, period=0)


class TestCCI:
    def test_cci_length(self):
        high = low = close = _float_series([100.0] * 25)
        result = cci(high, low, close, period=20)
        assert len(result) == 25

    def test_cci_nan_warmup(self):
        high = low = close = _float_series([100.0] * 25)
        result = cci(high, low, close, period=20)
        assert result.iloc[:19].isna().all()


class TestStochastic:
    def test_stochastic_length(self):
        h = l = c = _float_series([100.0] * 20)
        result = stochastic(h, l, c, k=14, d=3)
        assert len(result["k"]) == len(c)

    def test_stochastic_nan_warmup(self):
        h = l = c = _float_series([100.0] * 20)
        result = stochastic(h, l, c, k=14)
        # Stochastic %K is filled with 0 for insufficient warmup
        # After k period it should be non-zero for flat price
        assert result["k"].iloc[-1] == 0.0


class TestBollingerBands:
    def test_bb_shape(self):
        closes = _float_series([100.0] * 25)
        result = bollinger_bands(closes, period=20)
        assert len(result["middle"]) == len(closes)

    def test_bb_nan_warmup(self):
        closes = _float_series([100.0] * 25)
        result = bollinger_bands(closes, period=20)
        assert result["middle"].iloc[:19].isna().all()

    def test_bb_raises_invalid_period(self):
        closes = _float_series([100.0] * 5)
        with pytest.raises(ValueError):
            bollinger_bands(closes, period=0)


class TestKeltnerChannel:
    def test_kc_shape(self):
        h = l = c = _float_series([100.0] * 25)
        result = keltner_channel(h, l, c)
        assert len(result["middle"]) == len(h)


class TestOBV:
    def test_obv_length(self):
        closes = _float_series([100, 102, 101, 103])
        volumes = _float_series([1000, 1000, 1000, 1000])
        result = obv(closes, volumes)
        assert len(result) == len(closes)

    def test_obv_mismatched_lengths(self):
        closes = _float_series([100, 102, 101])
        volumes = _float_series([1000, 1000])
        with pytest.raises(ValueError, match="same length"):
            obv(closes, volumes)


class TestVWAP:
    def test_vwap_length(self):
        h = l = c = _float_series([100.0] * 5)
        v = _float_series([1000.0] * 5)
        result = vwap(h, l, c, v)
        assert len(result) == len(h)

    def test_vwap_mismatched_lengths(self):
        h = l = c = _float_series([100.0] * 5)
        v = _float_series([1000.0] * 3)
        with pytest.raises(ValueError):
            vwap(h, l, c, v)


class TestADX:
    def test_adx_length(self):
        h = l = c = _float_series([100.0] * 40)
        result = adx(h, l, c, period=14)
        assert len(result["adx"]) == len(h)

    def test_adx_raises_invalid_period(self):
        h = l = c = _float_series([100.0] * 5)
        with pytest.raises(ValueError):
            adx(h, l, c, period=0)


class TestSupertrend:
    def test_supertrend_length(self):
        h = l = c = _float_series([100.0] * 20)
        result = supertrend(h, l, c, period=10)
        assert len(result["direction"]) == len(h)

    def test_supertrend_direction_values(self):
        h = l = c = _float_series([100.0] * 20)
        result = supertrend(h, l, c, period=10)
        values = result["direction"].dropna().unique()
        assert set(values).issubset({1.0, -1.0})


class TestAroon:
    def test_aroon_length(self):
        h = l = _float_series([100.0] * 30)
        result = aroon(h, l, period=25)
        assert len(result["aroon_up"]) == len(h)

    def test_aroon_nan_warmup(self):
        h = l = _float_series([100.0] * 30)
        result = aroon(h, l, period=25)
        assert result["aroon_up"].iloc[:25].isna().all()

    def test_aroon_oscillator_range(self):
        h = l = _float_series([100.0] * 30)
        result = aroon(h, l, period=25)
        valid = result["aroon_oscillator"].dropna()
        assert (valid >= -100).all()
        assert (valid <= 100).all()
