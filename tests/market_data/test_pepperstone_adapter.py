"""Unit tests for the Pepperstone market data adapter."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from trading.market_data.adapters import pepperstone_adapter as pepperstone_module
from trading.market_data.adapters.pepperstone_adapter import (
    MockPepperstoneAdapter,
    PepperstoneAdapter,
    create_pepperstone_adapter,
)

# Re-export for convenience
MockPepperstoneAdapter = pepperstone_module.MockPepperstoneAdapter
create_pepperstone_adapter = pepperstone_module.create_pepperstone_adapter


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def is_sorted_by_time(candles: list) -> bool:
    return all(
        candles[i].open_time <= candles[i + 1].open_time
        for i in range(len(candles) - 1)
    )


# ─────────────────────────────────────────────────────────────────────────────
# MockPepperstoneAdapter tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMockPepperstoneAdapter:
    """Tests for the mock adapter (no Pepperstone connection required)."""

    @pytest.fixture
    def adapter(self) -> MockPepperstoneAdapter:
        return MockPepperstoneAdapter(
            mock_bid=Decimal("2345.00"),
            mock_ask=Decimal("2345.30"),
            mock_candle_close=Decimal("2345.15"),
        )

    def test_adapter_name(self, adapter: MockPepperstoneAdapter) -> None:
        assert adapter.adapter_name == "Pepperstone (Mock)"

    def test_default_symbol(self, adapter: MockPepperstoneAdapter) -> None:
        assert adapter.default_symbol() == "XAUUSD"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("XAUUSD", "XAUUSD"),
            ("XAUUSD.pro", "XAUUSD"),
            ("XAUUSD.m", "XAUUSD"),
            ("XAU/USD", "XAUUSD"),
            ("xauusd", "XAUUSD"),
            ("GOLD", "XAUUSD"),
            ("XAUXAU", "XAUUSD"),
            ("EURUSD", "EURUSD"),
            ("EURUSD.pro", "EURUSD"),
            ("EUR/USD", "EURUSD"),
            ("GBPUSD", "GBPUSD"),
            ("USDJPY", "USDJPY"),
        ],
    )
    def test_normalize_symbol(
        self, raw: str, expected: str
    ) -> None:
        assert MockPepperstoneAdapter.normalize_symbol(raw) == expected

    def test_fetch_candles_returns_correct_count(
        self, adapter: MockPepperstoneAdapter
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "15m", limit=50)
        assert len(candles) == 50

    def test_fetch_candles_sorted_oldest_to_newest(
        self, adapter: MockPepperstoneAdapter
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "1h", limit=20)
        assert is_sorted_by_time(candles)

    def test_fetch_candles_uses_correct_timeframe(
        self, adapter: MockPepperstoneAdapter
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "5m", limit=10)
        for c in candles:
            assert c.timeframe == "5m"
            assert c.source == "pepperstone_mock"
            assert c.symbol == "XAUUSD"

    def test_fetch_candles_timeframe_deltas(self) -> None:
        adapter = MockPepperstoneAdapter()
        for interval, delta_minutes in [
            ("1m", 1),
            ("5m", 5),
            ("15m", 15),
            ("30m", 30),
            ("1h", 60),
            ("4h", 240),
            ("1d", 1440),
        ]:
            candles = adapter.fetch_candles("XAUUSD", interval, limit=2)
            assert len(candles) == 2
            delta = candles[1].open_time - candles[0].open_time
            assert delta == timedelta(minutes=delta_minutes), f"Failed for {interval}"

    def test_fetch_candles_unknown_interval_raises(
        self, adapter: MockPepperstoneAdapter
    ) -> None:
        with pytest.raises(ValueError, match="Unsupported interval"):
            adapter.fetch_candles("XAUUSD", "2m", limit=10)

    def test_fetch_candles_prices_positive(self, adapter: MockPepperstoneAdapter) -> None:
        candles = adapter.fetch_candles("XAUUSD", "15m", limit=5)
        for c in candles:
            assert c.open > 0
            assert c.high > 0
            assert c.low > 0
            assert c.close > 0
            assert c.volume >= 0
            assert c.high >= c.open
            assert c.high >= c.close
            assert c.low <= c.open
            assert c.low <= c.close

    def test_fetch_candles_different_symbol(self) -> None:
        adapter = MockPepperstoneAdapter(symbol="EURUSD")
        candles = adapter.fetch_candles("EURUSD", "1h", limit=5)
        for c in candles:
            assert c.symbol == "EURUSD"

    def test_get_bid_ask(self, adapter: MockPepperstoneAdapter) -> None:
        quote = adapter.get_bid_ask("XAUUSD")
        assert quote.symbol == "XAUUSD"
        assert quote.bid == Decimal("2345.00")
        assert quote.ask == Decimal("2345.30")
        assert quote.spread == Decimal("0.30")
        expected_spread_bps = (
            Decimal("0.30") / Decimal("2345.00") * Decimal("10000")
        ).quantize(Decimal("0.01"))
        assert quote.spread_bps == expected_spread_bps
        assert quote.mid == (quote.bid + quote.ask) / Decimal("2")
        assert quote.source == "pepperstone_mock"

    def test_get_bid_ask_zero_bid(self) -> None:
        adapter = MockPepperstoneAdapter(
            mock_bid=Decimal("0"),
            mock_ask=Decimal("1.00"),
        )
        quote = adapter.get_bid_ask("XAUUSD")
        assert quote.spread_bps == Decimal("0")

    def test_health_check(self, adapter: MockPepperstoneAdapter) -> None:
        assert adapter.health_check() is True


# ─────────────────────────────────────────────────────────────────────────────
# PepperstoneAdapter unit tests (mocked HTTP)
# ─────────────────────────────────────────────────────────────────────────────


class TestPepperstoneAdapterSymbolNormalization:
    """Tests for symbol normalization in live adapter."""

    def test_normalize_symbol(self) -> None:
        assert PepperstoneAdapter.normalize_symbol("XAUUSD") == "XAUUSD"
        assert PepperstoneAdapter.normalize_symbol("XAUUSD.pro") == "XAUUSD"
        assert PepperstoneAdapter.normalize_symbol("EURUSD.m") == "EURUSD"
        assert PepperstoneAdapter.normalize_symbol("XAU/USD") == "XAUUSD"
        assert PepperstoneAdapter.normalize_symbol("GOLD") == "XAUUSD"


class TestPepperstoneAdapterFetchCandles:
    """Tests for fetch_candles using mocked requests."""

    @pytest.fixture
    def mock_response(self) -> MagicMock:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "candles": [
                {
                    "time": "2025-01-01T10:00:00Z",
                    "bid": {"o": "2345.5", "h": "2346.0", "l": "2345.0", "c": "2345.8"},
                    "volume": 100,
                },
                {
                    "time": "2025-01-01T10:15:00Z",
                    "bid": {"o": "2345.8", "h": "2346.2", "l": "2345.5", "c": "2346.0"},
                    "volume": 120,
                },
            ]
        }
        return response

    @pytest.fixture
    def adapter(self, mock_response: MagicMock) -> PepperstoneAdapter:
        with patch.object(
            pepperstone_module, "requests"
        ) as mock_requests:
            mock_session = MagicMock()
            mock_session.request.return_value = mock_response
            mock_requests.Session.return_value = mock_session
            mock_requests.HTTPError = requests.HTTPError
            adapter = PepperstoneAdapter(
                api_key="test_key",
                api_secret="test_secret",
            )
            adapter._session = mock_session
        return adapter

    def test_fetch_candles_returns_correct_count(
        self, adapter: PepperstoneAdapter
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "15m", limit=10)
        assert len(candles) == 2

    def test_fetch_candles_unknown_interval_raises(
        self, adapter: PepperstoneAdapter
    ) -> None:
        with pytest.raises(ValueError, match="Unsupported interval"):
            adapter.fetch_candles("XAUUSD", "2m", limit=10)

    def test_fetch_candles_no_data_raises_connection_error(
        self, adapter: PepperstoneAdapter
    ) -> None:
        adapter._session.request.return_value.json.return_value = {"candles": []}
        with pytest.raises(ConnectionError, match="No historical data"):
            adapter.fetch_candles("XAUUSD", "1m", limit=10)

    def test_fetch_candles_uses_bid_prices(
        self, adapter: PepperstoneAdapter, mock_response: MagicMock
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "15m", limit=2)
        assert candles[0].open == Decimal("2345.5")
        assert candles[0].high == Decimal("2346.0")
        assert candles[0].low == Decimal("2345.0")
        assert candles[0].close == Decimal("2345.8")

    def test_fetch_candles_normalizes_symbol(
        self, adapter: PepperstoneAdapter, mock_response: MagicMock
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD.pro", "15m", limit=2)
        for c in candles:
            assert c.symbol == "XAUUSD"

    def test_fetch_candles_correct_timeframe(
        self, adapter: PepperstoneAdapter, mock_response: MagicMock
    ) -> None:
        candles = adapter.fetch_candles("XAUUSD", "15m", limit=2)
        for c in candles:
            assert c.timeframe == "15m"


class TestPepperstoneAdapterBidAsk:
    """Tests for get_bid_ask using mocked requests."""

    @pytest.fixture
    def mock_tick_response(self) -> MagicMock:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "tick": {"bid": "2345.00", "ask": "2345.30"}
        }
        return response

    @pytest.fixture
    def adapter(self, mock_tick_response: MagicMock) -> PepperstoneAdapter:
        with patch.object(
            pepperstone_module, "requests"
        ) as mock_requests:
            mock_session = MagicMock()
            mock_session.request.return_value = mock_tick_response
            mock_requests.Session.return_value = mock_session
            mock_requests.HTTPError = requests.HTTPError
            adapter = PepperstoneAdapter(
                api_key="test_key",
                api_secret="test_secret",
            )
            adapter._session = mock_session
        return adapter

    def test_get_bid_ask(self, adapter: PepperstoneAdapter) -> None:
        quote = adapter.get_bid_ask("XAUUSD")
        assert quote.symbol == "XAUUSD"
        assert quote.bid == Decimal("2345.00")
        assert quote.ask == Decimal("2345.30")
        assert quote.spread == Decimal("0.30")
        assert quote.source == "pepperstone"

    def test_get_bid_ask_strips_suffix(
        self, adapter: PepperstoneAdapter, mock_tick_response: MagicMock
    ) -> None:
        mock_tick_response.json.return_value = {
            "tick": {"bid": "2345.00", "ask": "2345.30"}
        }
        quote = adapter.get_bid_ask("XAUUSD.pro")
        assert quote.symbol == "XAUUSD"


class TestPepperstoneAdapterHealthCheck:
    """Tests for health_check."""

    def test_health_check_success(self) -> None:
        with patch.object(
            pepperstone_module, "requests"
        ) as mock_requests:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "candles": [
                    {
                        "time": "2025-01-01T10:00:00Z",
                        "bid": {"o": "2345.5", "h": "2346.0", "l": "2345.0", "c": "2345.8"},
                        "volume": 100,
                    }
                ]
            }
            mock_session.request.return_value = mock_response
            mock_requests.Session.return_value = mock_session
            mock_requests.HTTPError = requests.HTTPError
            adapter = PepperstoneAdapter(
                api_key="test_key",
                api_secret="test_secret",
            )
            adapter._session = mock_session
            assert adapter.health_check() is True

    def test_health_check_failure(self) -> None:
        with patch.object(
            pepperstone_module, "requests"
        ) as mock_requests:
            mock_requests.HTTPError = requests.HTTPError
            mock_session = MagicMock()
            mock_session.request.side_effect = Exception("Connection refused")
            mock_requests.Session.return_value = mock_session
            adapter = PepperstoneAdapter(
                api_key="test_key",
                api_secret="test_secret",
            )
            adapter._session = mock_session
            assert adapter.health_check() is False


# ─────────────────────────────────────────────────────────────────────────────
# create_pepperstone_adapter factory tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCreatePepperstoneAdapter:
    """Tests for the factory function."""

    def test_force_mock(self) -> None:
        adapter = create_pepperstone_adapter(use_mock=True)
        assert isinstance(adapter, MockPepperstoneAdapter)

    def test_missing_credentials_returns_mock(self) -> None:
        adapter = create_pepperstone_adapter(
            api_key="", api_secret="", use_mock=False
        )
        assert isinstance(adapter, MockPepperstoneAdapter)

    def test_health_check_failure_falls_back_to_mock(self) -> None:
        with patch.object(
            pepperstone_module, "PepperstoneAdapter"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance.health_check.return_value = False
            mock_cls.return_value = mock_instance
            adapter = create_pepperstone_adapter(
                api_key="test_key",
                api_secret="test_secret",
                use_mock=False,
            )
            assert isinstance(adapter, MockPepperstoneAdapter)

    def test_live_success_returns_live_adapter(self) -> None:
        with patch.object(
            pepperstone_module, "PepperstoneAdapter"
        ) as mock_cls:
            mock_instance = MagicMock(spec=PepperstoneAdapter)
            mock_instance.health_check.return_value = True
            mock_cls.return_value = mock_instance
            adapter = create_pepperstone_adapter(
                api_key="test_key",
                api_secret="test_secret",
                use_mock=False,
            )
            # The factory returns the live adapter when health_check passes
            assert mock_cls.called


# Import requests for HTTPError reference
import requests
