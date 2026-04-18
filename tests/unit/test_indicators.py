from decimal import Decimal

import pytest

from trading.features.indicators import atr, ema, rsi, true_range


class TestEma:
    def test_returns_same_length(self):
        values = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104")]
        result = ema(values, period=3)
        assert len(result) == len(values)
        # multiplier = 2/(3+1) = 0.5
        # seed = SMA(100,101,102) = 101
        # result[2] = 101
        # result[3] = 0.5*(103-101)+101 = 102
        # result[4] = 0.5*(104-102)+102 = 103
        assert result == [None, None, Decimal("101"), Decimal("102"), Decimal("103")]

    def test_first_valid_value_at_period_minus_one(self):
        values = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40"), Decimal("50")]
        result = ema(values, period=3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] is not None
        # period-1 = index 2, value should be SMA of first 3 = 20
        assert result[2] == Decimal("20")

    def test_raises_on_invalid_period(self):
        values = [Decimal("1"), Decimal("2")]
        with pytest.raises(ValueError, match="period must be >= 1"):
            ema(values, period=0)
        with pytest.raises(ValueError, match="period must be >= 1"):
            ema(values, period=-1)

    def test_empty_input(self):
        result = ema([], period=14)
        assert result == []

    def test_shorter_than_period(self):
        values = [Decimal("10"), Decimal("20")]
        result = ema(values, period=5)
        assert all(v is None for v in result)


class TestRsi:
    def test_returns_values_between_0_and_100(self):
        # Steady climb: all positive changes
        values = [
            Decimal("100"), Decimal("102"), Decimal("104"), Decimal("106"),
            Decimal("108"), Decimal("110"), Decimal("112"), Decimal("114"),
            Decimal("116"), Decimal("118"), Decimal("120"), Decimal("122"),
            Decimal("124"), Decimal("126"), Decimal("128"), Decimal("130"),
        ]
        result = rsi(values, period=14)
        valid_values = [v for v in result if v is not None]
        assert len(valid_values) > 0
        assert all(Decimal("0") <= v <= Decimal("100") for v in valid_values)

    def test_returns_100_when_no_losses(self):
        values = [
            Decimal("100"), Decimal("105"), Decimal("110"), Decimal("115"),
            Decimal("120"), Decimal("125"), Decimal("130"), Decimal("135"),
            Decimal("140"), Decimal("145"), Decimal("150"), Decimal("155"),
            Decimal("160"), Decimal("165"), Decimal("170"),
        ]
        result = rsi(values, period=14)
        valid = [v for v in result if v is not None]
        assert len(valid) > 0
        # Should be 100 when there are no losses
        assert valid[-1] == Decimal("100")

    def test_raises_on_invalid_period(self):
        values = [Decimal("100"), Decimal("101")]
        with pytest.raises(ValueError, match="period must be >= 1"):
            rsi(values, period=0)


class TestTrueRange:
    def test_handles_missing_previous_close(self):
        result = true_range(Decimal("105"), Decimal("95"), None)
        assert result == Decimal("10")

    def test_normal_case(self):
        result = true_range(Decimal("105"), Decimal("95"), Decimal("100"))
        # high - low = 10, high - prev_close = 5, low - prev_close = 5
        assert result == Decimal("10")

    def test_gap_up(self):
        # high=105, low=100, prev_close=90
        result = true_range(Decimal("105"), Decimal("100"), Decimal("90"))
        assert result == Decimal("15")

    def test_gap_down(self):
        # high=100, low=95, prev_close=105
        # high-low=5, |high-prev|=5, |low-prev|=10 → max=10
        result = true_range(Decimal("100"), Decimal("95"), Decimal("105"))
        assert result == Decimal("10")


class TestAtr:
    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            atr(
                [Decimal("100"), Decimal("101")],
                [Decimal("99"), Decimal("100"), Decimal("101")],
                [Decimal("100"), Decimal("101")],
            )

    def test_returns_none_until_warmup(self):
        highs = [Decimal("105"), Decimal("110"), Decimal("115")]
        lows = [Decimal("95"), Decimal("100"), Decimal("105")]
        closes = [Decimal("100"), Decimal("105"), Decimal("110")]
        result = atr(highs, lows, closes, period=14)
        assert all(v is None for v in result)

    def test_returns_same_length(self):
        highs = [Decimal("105"), Decimal("110"), Decimal("115"), Decimal("120")]
        lows = [Decimal("95"), Decimal("100"), Decimal("105"), Decimal("110")]
        closes = [Decimal("100"), Decimal("105"), Decimal("110"), Decimal("115")]
        result = atr(highs, lows, closes, period=2)
        assert len(result) == len(highs)
        assert result[0] is None
        assert result[1] is not None

    def test_raises_on_invalid_period(self):
        with pytest.raises(ValueError, match="period must be >= 1"):
            atr(
                [Decimal("105"), Decimal("110")],
                [Decimal("95"), Decimal("100")],
                [Decimal("100"), Decimal("105")],
                period=0,
            )
