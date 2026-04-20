"""Unit tests for binance_filters module."""

from decimal import Decimal

from trading.execution.binance_filters import (
    BinanceFilters,
    SymbolFilters,
    floor_to_step,
    round_to_tick,
)


class TestSymbolFilters:
    def test_from_binance_parses_all_filters(self):
        filters = [
            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
        ]
        sf = SymbolFilters.from_binance(filters)
        assert sf.min_notional == Decimal("10")
        assert sf.step_size == Decimal("0.001")
        assert sf.tick_size == Decimal("0.01")

    def test_from_binance_handles_missing_filters(self):
        sf = SymbolFilters.from_binance([])
        assert sf.min_notional == Decimal("0")
        assert sf.step_size == Decimal("1")
        assert sf.tick_size == Decimal("0.00000001")

    def test_from_binance_uses_last_value_for_duplicates(self):
        filters = [
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
        ]
        sf = SymbolFilters.from_binance(filters)
        assert sf.min_notional == Decimal("10")


class TestBinanceFiltersCache:
    def test_get_filters_returns_none_when_not_cached(self):
        bf = BinanceFilters()
        assert bf.get_filters("BTCUSDT") is None

    def test_format_quantity_returns_none_when_not_cached(self):
        bf = BinanceFilters()
        result = bf.format_quantity("BTCUSDT", Decimal("1.5"))
        assert result is None

    def test_format_price_returns_none_when_not_cached(self):
        bf = BinanceFilters()
        result = bf.format_price("BTCUSDT", Decimal("100"))
        assert result is None

    def test_validate_min_notional_returns_false_when_not_cached(self):
        bf = BinanceFilters()
        assert bf.validate_min_notional("BTCUSDT", Decimal("1"), Decimal("100")) is False

    def test_format_quantity_floors_to_step_size(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
        )
        result = bf.format_quantity("BTCUSDT", Decimal("1.55555"))
        assert result == Decimal("1.555")

    def test_format_quantity_rounds_down_only(self):
        bf = BinanceFilters()
        bf._filters["ETHUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.01"),
            tick_size=Decimal("0.001"),
        )
        # 1.99999 floored to step 0.01 = 1.99
        result = bf.format_quantity("ETHUSDT", Decimal("1.99999"))
        assert result == Decimal("1.99")
        # 0.015 floored to step 0.01 = 0.01 (stays above zero)
        result2 = bf.format_quantity("ETHUSDT", Decimal("0.015"))
        assert result2 == Decimal("0.01")

    def test_format_quantity_returns_none_for_zero_or_negative(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
        )
        assert bf.format_quantity("BTCUSDT", Decimal("0")) is None
        assert bf.format_quantity("BTCUSDT", Decimal("-1")) is None

    def test_format_quantity_returns_none_when_floors_to_zero(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.01"),
            tick_size=Decimal("0.01"),
        )
        # qty=0.004, step=0.01 -> 0.00 -> None
        assert bf.format_quantity("BTCUSDT", Decimal("0.004")) is None

    def test_format_price_rounds_to_tick_size(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
        )
        result = bf.format_price("BTCUSDT", Decimal("100.555"))
        assert result == Decimal("100.55")

    def test_validate_min_notional_passes_when_met(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
        )
        # 0.1 * 100 = 10, meets minNotional
        assert bf.validate_min_notional("BTCUSDT", Decimal("0.1"), Decimal("100")) is True

    def test_validate_min_notional_fails_when_not_met(self):
        bf = BinanceFilters()
        bf._filters["BTCUSDT"] = SymbolFilters(
            min_notional=Decimal("10"),
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
        )
        # 0.01 * 100 = 1, below minNotional
        assert bf.validate_min_notional("BTCUSDT", Decimal("0.01"), Decimal("100")) is False


class TestFloorToStep:
    def test_floors_to_step(self):
        assert floor_to_step(Decimal("1.555"), Decimal("0.001")) == Decimal("1.555")
        assert floor_to_step(Decimal("1.5555"), Decimal("0.001")) == Decimal("1.555")
        assert floor_to_step(Decimal("1.999"), Decimal("0.01")) == Decimal("1.99")

    def test_rounds_down_not_up(self):
        # 0.999 rounded down to 0.99
        assert floor_to_step(Decimal("0.999"), Decimal("0.01")) == Decimal("0.99")
        # 0.009 rounded down to 0.00
        assert floor_to_step(Decimal("0.009"), Decimal("0.01")) == Decimal("0")


class TestRoundToTick:
    def test_round_to_tick_preserves_aligned_values(self):
        # Value already on tick boundary passes through unchanged
        assert round_to_tick(Decimal("100.55"), Decimal("0.01")) == Decimal("100.55")
        assert round_to_tick(Decimal("100.00"), Decimal("0.01")) == Decimal("100.00")

    def test_rounds_down_to_tick(self):
        # ROUND_DOWN truncates: 100.555 -> 100.55, 100.559 -> 100.55
        assert round_to_tick(Decimal("100.555"), Decimal("0.01")) == Decimal("100.55")
        assert round_to_tick(Decimal("100.559"), Decimal("0.01")) == Decimal("100.55")
        # 100.556 -> 100.55 (round down to nearest tick, not up)
        assert round_to_tick(Decimal("100.556"), Decimal("0.01")) == Decimal("100.55")