"""Unit tests for live_executor module."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from trading.execution.binance_filters import BinanceFilters, SymbolFilters
from trading.execution.live_executor import LiveExecutor, LiveExecutorConfig


@pytest.fixture
def disabled_config() -> LiveExecutorConfig:
    return LiveExecutorConfig(
        allowed_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        live_trading_enabled=False,
    )


@pytest.fixture
def enabled_config() -> LiveExecutorConfig:
    return LiveExecutorConfig(
        allowed_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        live_trading_enabled=True,
    )


@pytest.fixture
def mock_binance_filters() -> BinanceFilters:
    bf = BinanceFilters()
    bf._filters["BTCUSDT"] = SymbolFilters(
        min_notional=Decimal("10"),
        step_size=Decimal("0.001"),
        tick_size=Decimal("0.01"),
    )
    bf._filters["ETHUSDT"] = SymbolFilters(
        min_notional=Decimal("10"),
        step_size=Decimal("0.01"),
        tick_size=Decimal("0.001"),
    )
    return bf


class TestLiveExecutorConfig:
    def test_config_default_base_url(self):
        cfg = LiveExecutorConfig(allowed_symbols=["BTCUSDT"], live_trading_enabled=True)
        assert cfg.base_url == "https://api.binance.com"

    def test_api_key_empty_rejected(self):
        with pytest.raises(ValueError, match="api_key"):
            LiveExecutor(
                LiveExecutorConfig(allowed_symbols=["BTCUSDT"], live_trading_enabled=True),
                api_key="",
                api_secret="secret",
            )

    def test_api_secret_whitespace_rejected(self):
        with pytest.raises(ValueError, match="api_secret"):
            LiveExecutor(
                LiveExecutorConfig(allowed_symbols=["BTCUSDT"], live_trading_enabled=True),
                api_key="key",
                api_secret="   ",
            )


class TestClientOrderIdGeneration:
    def test_generate_client_order_id_format(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        order_id = executor.generate_client_order_id(
            strategy_name="multi_timeframe_momentum",
            cycle_id="20260419_001",
            symbol="BTCUSDT",
            attempt=1,
        )
        assert order_id == "multi_timeframe_momentum-20260419_001-BTCUSDT-1"

    def test_generate_client_order_id_attempt_2(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        order_id = executor.generate_client_order_id(
            strategy_name="multi_timeframe_momentum",
            cycle_id="20260419_001",
            symbol="BTCUSDT",
            attempt=2,
        )
        assert order_id == "multi_timeframe_momentum-20260419_001-BTCUSDT-2"

    def test_idempotent_same_inputs_same_output(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        id1 = executor.generate_client_order_id("strategy", "cycle1", "BTCUSDT", 1)
        id2 = executor.generate_client_order_id("strategy", "cycle1", "BTCUSDT", 1)
        assert id1 == id2

    def test_different_symbols_produce_different_ids(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        id_btc = executor.generate_client_order_id("strategy", "cycle1", "BTCUSDT", 1)
        id_eth = executor.generate_client_order_id("strategy", "cycle1", "ETHUSDT", 1)
        assert id_btc != id_eth


class TestLiveTradingDisabledRejection:
    def test_place_market_buy_rejected_when_live_trading_disabled(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        result = executor.place_market_buy(
            symbol="BTCUSDT",
            qty=Decimal("0.1"),
            price=Decimal("100000"),
            strategy_name="strategy",
            cycle_id="cycle1",
        )
        assert result.success is False
        assert result.error_message == "live_trading_disabled"
        assert result.order_id is None

    def test_place_market_sell_rejected_when_live_trading_disabled(self, disabled_config):
        executor = LiveExecutor(disabled_config, api_key="test", api_secret="test")
        result = executor.place_market_sell(
            symbol="BTCUSDT",
            qty=Decimal("0.1"),
            price=Decimal("100000"),
            strategy_name="strategy",
            cycle_id="cycle1",
        )
        assert result.success is False
        assert result.error_message == "live_trading_disabled"
        assert result.order_id is None

    def test_unlisted_symbol_rejected_when_enabled(self, enabled_config, mock_binance_filters):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        result = executor.place_market_buy(
            symbol="DOGEUSDT",
            qty=Decimal("100"),
            price=Decimal("1"),
            strategy_name="strategy",
            cycle_id="cycle1",
        )
        assert result.success is False
        assert "symbol_not_allowed" in result.error_message


class TestFilterValidation:
    def test_min_notional_rejected_when_below_threshold(self, enabled_config, mock_binance_filters):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True
        # qty * price = 0.001 * 100 = 0.1, but minNotional is 10
        result = executor.place_market_buy(
            symbol="BTCUSDT",
            qty=Decimal("0.001"),
            price=Decimal("100"),
            strategy_name="strategy",
            cycle_id="cycle1",
        )
        assert result.success is False
        assert result.error_message == "filter_validation_failed"

    def test_valid_min_notional_passes_filter_no_http_call(
        self, enabled_config, mock_binance_filters
    ):
        """Filter passes but we mock _request to prevent real HTTP call."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.return_value = {"orderId": "12345", "clientOrderId": "test-id"}
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )
            # Mock API succeeds, filter already passed
            assert result.success is True
            assert result.order_id == "12345"

    def test_place_market_sell_filter_rejected_when_min_notional_fail(
        self, enabled_config, mock_binance_filters
    ):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True
        result = executor.place_market_sell(
            symbol="BTCUSDT",
            qty=Decimal("0.001"),
            price=Decimal("100"),
            strategy_name="strategy",
            cycle_id="cycle1",
        )
        assert result.success is False
        assert result.error_message == "filter_validation_failed"
        assert result.side == "SELL"


class TestContextManager:
    def test_close_called_on_context_exit(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor._client, "close") as mock_close:
            with executor:
                pass
            mock_close.assert_called_once()

    def test_close_can_be_called_directly(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor._client, "close") as mock_close:
            executor.close()
            mock_close.assert_called_once()


class TestAPIExceptionHandling:
    def test_exchange_info_fetch_failure_returns_structured_error(
        self, enabled_config, mock_binance_filters
    ):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        with patch.object(executor, "ensure_exchange_info") as mock_ensure:
            mock_ensure.side_effect = httpx.RequestError("network failure", request=MagicMock())
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )
            assert result.success is False
            assert result.error_message == "exchange_info_unavailable:RequestError"

    def test_http_error_returns_structured_error(self, enabled_config, mock_binance_filters):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = "binance error text"
            mock_request.side_effect = httpx.HTTPStatusError(
                message="400",
                request=MagicMock(),
                response=mock_response,
            )
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )
            assert result.success is False
            assert "http_error:400" in result.error_message
            assert result.client_order_id is not None

    def test_request_error_returns_structured_error(self, enabled_config, mock_binance_filters):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.side_effect = httpx.RequestError("connection refused", request=MagicMock())
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )
            assert result.success is False
            assert "request_error:RequestError" in result.error_message

    def test_get_order_status_returns_none_on_request_error(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor, "_request") as mock_request:
            mock_request.side_effect = httpx.RequestError("network failure", request=MagicMock())
            result = executor.get_order_status("BTCUSDT", "12345")
            assert result is None

    def test_get_order_status_returns_data_on_success(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor, "_request") as mock_request:
            mock_request.return_value = {
                "orderId": 12345,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "side": "BUY",
            }
            result = executor.get_order_status("BTCUSDT", "12345")
            assert result is not None
            assert result["orderId"] == 12345
            assert result["status"] == "FILLED"


class TestEnsureExchangeInfo:
    def test_ensure_exchange_info_calls_fetch_and_cache(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor.filters, "fetch_and_cache") as mock_fetch:
            executor.ensure_exchange_info()
            assert mock_fetch.call_count == 1
            call_args = mock_fetch.call_args
            # symbols passed as keyword arg
            assert call_args.kwargs.get("symbols") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_ensure_exchange_info_idempotent(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor.filters, "fetch_and_cache") as mock_fetch:
            executor.ensure_exchange_info()
            executor.ensure_exchange_info()
            # Only called once because _exchange_info_fetched is True after first call
            mock_fetch.assert_called_once()


class TestColdFilterAutoEnsure:
    """Tests for auto-ensure behavior when filters are not pre-warmed."""

    def test_place_market_buy_auto_ensures_on_cold_filters(self, enabled_config):
        """place_market_buy calls ensure_exchange_info before applying filters on cold start."""
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")

        with patch.object(executor, "ensure_exchange_info") as mock_ensure:
            filtered = (Decimal("0.1"), Decimal("100000"))
            with patch.object(executor, "_apply_filters", return_value=filtered):
                with patch.object(executor, "_request") as mock_request:
                    mock_request.return_value = {"orderId": "12345", "clientOrderId": "test-id"}
                    result = executor.place_market_buy(
                        symbol="BTCUSDT",
                        qty=Decimal("0.1"),
                        price=Decimal("100000"),
                        strategy_name="strategy",
                        cycle_id="cycle1",
                    )

            assert mock_ensure.call_count == 1
            assert result.success is True

    def test_place_market_sell_auto_ensures_on_cold_filters(self, enabled_config):
        """place_market_sell calls ensure_exchange_info before applying filters on cold start."""
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")

        with patch.object(executor, "ensure_exchange_info") as mock_ensure:
            filtered = (Decimal("0.1"), Decimal("100000"))
            with patch.object(executor, "_apply_filters", return_value=filtered):
                with patch.object(executor, "_request") as mock_request:
                    mock_request.return_value = {"orderId": "67890", "clientOrderId": "sell-id"}
                    result = executor.place_market_sell(
                        symbol="BTCUSDT",
                        qty=Decimal("0.1"),
                        price=Decimal("100000"),
                        strategy_name="strategy",
                        cycle_id="cycle1",
                    )

            assert mock_ensure.call_count == 1
            assert result.success is True

    def test_cold_filters_ensure_succeeds_but_filter_validation_fails(self, enabled_config):
        """When ensure succeeds but filters were never cached, filter_validation_failed returned."""
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        # No filters pre-warmed; ensure_exchange_info is a no-op since filters were never cached

        with patch.object(executor, "ensure_exchange_info"):  # succeeds (no-op)
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        # Without pre-warmed filters, format_quantity returns None -> filter_validation_failed
        assert result.success is False
        assert result.error_message == "filter_validation_failed"

    def test_warm_filters_skip_ensure_and_proceed_directly(
        self, enabled_config, mock_binance_filters
    ):
        """When filters are pre-warmed, fetch_and_cache is not called."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        # Simulate already-warmed state
        executor._exchange_info_fetched = True

        with patch.object(executor.filters, "fetch_and_cache") as mock_fetch:
            with patch.object(executor, "_request") as mock_request:
                mock_request.return_value = {"orderId": "12345", "clientOrderId": "test-id"}
                result = executor.place_market_buy(
                    symbol="BTCUSDT",
                    qty=Decimal("0.1"),
                    price=Decimal("100000"),
                    strategy_name="strategy",
                    cycle_id="cycle1",
                )

            # fetch_and_cache should not be called when already warm
            mock_fetch.assert_not_called()
            assert result.success is True

    def test_ensure_failure_returns_exchange_info_unavailable_no_exception_propagates(
        self, enabled_config
    ):
        """When ensure raises httpx error, no exception escapes — stable error returned."""
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")

        # Use the exact exception types that the code catches
        with patch.object(
            executor, "ensure_exchange_info",
            side_effect=httpx.RequestError("network unreachable", request=MagicMock())
        ):
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        # Stable machine-readable error, no exception propagates
        assert result.success is False
        assert "exchange_info_unavailable" in result.error_message

    def test_ensure_http_error_returns_stable_error(self, enabled_config, mock_binance_filters):
        """When ensure_exchange_info raises HTTPStatusError, stable error returned."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_response)
        with patch.object(executor, "ensure_exchange_info", side_effect=exc):
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.success is False
        assert result.error_message == "exchange_info_unavailable:HTTPStatusError"

    def test_unexpected_exception_returns_internal_error(
        self, enabled_config, mock_binance_filters
    ):
        """Unexpected non-httpx exceptions should return internal_error (not request_error)."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request", side_effect=RuntimeError("boom")):
            result = executor.place_market_buy(
                symbol="BTCUSDT",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.success is False
        assert result.error_message == "internal_error"
