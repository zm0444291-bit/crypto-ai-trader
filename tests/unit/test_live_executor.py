"""Unit tests for live_executor module."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from trading.execution.binance_filters import BinanceFilters, SymbolFilters
from trading.execution.live_executor import (
    ErrorKind,
    ExecutionResult,
    LiveExecutor,
    LiveExecutorConfig,
    OrderLifecycle,
    OrderStatus,
)


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
            assert "exchange_info_unavailable" in result.error_message
            assert "network_error" in result.error_message

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
            assert "exchange_http_error:400" in result.error_message
            assert result.client_order_id is not None

    def test_request_error_returns_pending_unknown_with_query_fallback(
        self, enabled_config, mock_binance_filters
    ):
        """RequestError on submit triggers query fallback; fallback fails -> pending_unknown."""
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
            # After refactor: RequestError -> PENDING_UNKNOWN via query fallback.
            # If query also fails, we get "submit_timeout_query_failed:..."
            msg = result.error_message or ""
            assert "submit_timeout" in msg or "network_error" in msg

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
        assert "exchange_info_unavailable" in result.error_message
        assert "http_429" in result.error_message

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


class TestOrderLifecycleAndQueryFallback:
    """Tests for ExecutionResult structure, lifecycle states, and query fallback."""

    def test_execute_market_order_returns_execution_result_on_success(
        self, enabled_config, mock_binance_filters
    ):
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.return_value = {
                "orderId": "12345",
                "clientOrderId": "strategy-cycle1-BTCUSDT-1",
                "status": "FILLED",
                "fills": [
                    {"price": "100000.00", "qty": "0.1"},
                ],
            }
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert result.status == OrderStatus.FILLED
        assert result.code == "ok"
        assert result.client_order_id == "strategy-cycle1-BTCUSDT-1"
        assert result.exchange_order_id == "12345"
        assert result.retriable is False

    def test_submit_timeout_then_query_finds_filled(
        self, enabled_config, mock_binance_filters
    ):
        """Submit times out (RequestError) but query-by-clientOrderId finds FILLED."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        submit_response = MagicMock()
        submit_response.status_code = 200
        filled_response = {
            "orderId": "99999",
            "clientOrderId": "strategy-cycle1-BTCUSDT-1",
            "status": "FILLED",
        }

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.RequestError("connection reset", request=MagicMock())
            return filled_response

        with patch.object(executor, "_request", side_effect=side_effect):
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.FILLED
        assert result.code == "ok"
        assert result.client_order_id == "strategy-cycle1-BTCUSDT-1"
        assert result.exchange_order_id == "99999"
        assert result.message == "confirmed_via_query:FILLED"

    def test_submit_timeout_and_query_not_found_returns_pending_unknown(
        self, enabled_config, mock_binance_filters
    ):
        """Submit times out, query also returns nothing -> pending_unknown."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.side_effect = httpx.RequestError("timeout", request=MagicMock())
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.PENDING_UNKNOWN
        assert result.code == ErrorKind.PENDING_UNKNOWN.value
        code_or_msg = result.code.lower() if result.code else ""
        msg = result.message.lower() if result.message else ""
        assert "pending_unknown" in code_or_msg or "submit_timeout" in msg
        assert result.client_order_id == "strategy-cycle1-BTCUSDT-1"
        assert result.retriable is True

    def test_submit_timeout_but_query_returns_http_error(
        self, enabled_config, mock_binance_filters
    ):
        """Submit times out (RequestError), but query returns HTTP error (e.g., 429)."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        def submit_side_effect(*args, **kwargs):
            if args[0] == "POST":
                raise httpx.RequestError("timeout", request=MagicMock())
            # GET for query — return HTTP error (429 rate limited)
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_resp)
            raise exc

        with patch.object(executor, "_request", side_effect=submit_side_effect):
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.PENDING_UNKNOWN
        # HTTP error on query is classified as EXCHANGE_HTTP_ERROR
        assert result.code == ErrorKind.EXCHANGE_HTTP_ERROR.value
        assert "query_failed" in result.message
        assert result.retriable is True

    def test_http_4xx_returns_rejected_not_network_error(
        self, enabled_config, mock_binance_filters
    ):
        """HTTP 4xx is exchange_http_error, not network_error."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_request.side_effect = httpx.HTTPStatusError(
                "rate limited", request=MagicMock(), response=mock_response
            )
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.REJECTED
        assert result.code == ErrorKind.EXCHANGE_HTTP_ERROR.value
        assert "exchange_http_error" in result.code
        # 429 (rate limit) is retriable
        assert result.retriable is True

    def test_http_5xx_returns_rejected_not_network_error(
        self, enabled_config, mock_binance_filters
    ):
        """HTTP 5xx is exchange_http_error, not network_error."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 502
            mock_request.side_effect = httpx.HTTPStatusError(
                "bad gateway", request=MagicMock(), response=mock_response
            )
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.REJECTED
        assert result.code == ErrorKind.EXCHANGE_HTTP_ERROR.value
        assert "exchange_http_error" in result.code
        # 5xx are retriable (transient server errors)
        assert result.retriable is True

    def test_network_error_returns_pending_unknown_with_retriable_true(
        self, enabled_config, mock_binance_filters
    ):
        """RequestError (network/timeout) on submit -> pending_unknown, retriable=True."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.side_effect = httpx.RequestError("connection refused", request=MagicMock())
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.PENDING_UNKNOWN
        # code may be network_error (submit timeout, query succeeded)
        # or pending_unknown (both submit and query failed)
        assert result.code in (ErrorKind.NETWORK_ERROR.value, ErrorKind.PENDING_UNKNOWN.value)
        assert result.retriable is True

    def test_internal_error_returns_failed_code_not_network_or_http(
        self, enabled_config, mock_binance_filters
    ):
        """Unexpected Exception should be internal_error, not request_error."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request", side_effect=RuntimeError("unexpected")):
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="BUY",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.status == OrderStatus.FAILED
        assert result.code == ErrorKind.INTERNAL_ERROR.value
        assert result.retriable is False

    def test_retriable_flag_is_true_for_network_errors(
        self, enabled_config, mock_binance_filters
    ):
        """Only network errors should be retriable."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_request.side_effect = httpx.RequestError("timeout", request=MagicMock())
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="SELL",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.retriable is True

    def test_retriable_flag_is_false_for_http_errors(
        self, enabled_config, mock_binance_filters
    ):
        """HTTP errors should not be retriable (exchange knows the outcome)."""
        executor = LiveExecutor(
            enabled_config, api_key="test", api_secret="test", filters=mock_binance_filters
        )
        executor._exchange_info_fetched = True

        with patch.object(executor, "_request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_request.side_effect = httpx.HTTPStatusError(
                "bad request", request=MagicMock(), response=mock_response
            )
            result = executor.execute_market_order(
                symbol="BTCUSDT",
                side="SELL",
                qty=Decimal("0.1"),
                price=Decimal("100000"),
                strategy_name="strategy",
                cycle_id="cycle1",
            )

        assert result.retriable is False


class TestOrderLifecycleHelper:
    """Tests for OrderLifecycle helper and exchange status mapping."""

    def test_exchange_status_to_lifecycle_status_new(self):
        assert OrderLifecycle.exchange_status_to_lifecycle_status("NEW") == OrderStatus.ACKED

    def test_exchange_status_to_lifecycle_status_partially_filled(self):
        assert (
            OrderLifecycle.exchange_status_to_lifecycle_status("PARTIALLY_FILLED")
            == OrderStatus.PARTIALLY_FILLED
        )

    def test_exchange_status_to_lifecycle_status_filled(self):
        assert OrderLifecycle.exchange_status_to_lifecycle_status("FILLED") == OrderStatus.FILLED

    def test_exchange_status_to_lifecycle_status_canceled(self):
        assert (
            OrderLifecycle.exchange_status_to_lifecycle_status("CANCELED")
            == OrderStatus.CANCELED
        )

    def test_exchange_status_to_lifecycle_status_rejected(self):
        assert (
            OrderLifecycle.exchange_status_to_lifecycle_status("REJECTED")
            == OrderStatus.REJECTED
        )

    def test_exchange_status_to_lifecycle_status_expired(self):
        assert (
            OrderLifecycle.exchange_status_to_lifecycle_status("EXPIRED")
            == OrderStatus.EXPIRED
        )

    def test_exchange_status_to_lifecycle_status_unknown(self):
        assert (
            OrderLifecycle.exchange_status_to_lifecycle_status("UNKNOWN_STATUS")
            == OrderStatus.FAILED
        )

    def test_query_by_client_order_id_returns_order_on_success(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor._client, "request") as mock_request:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "orderId": "12345",
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "side": "BUY",
            }
            mock_response.raise_for_status = MagicMock()
            mock_request.return_value = mock_response
            lifecycle = OrderLifecycle(executor._client, executor.api_key, executor.api_secret)
            result = lifecycle.query_by_client_order_id("BTCUSDT", "test-client-id")

        assert result is not None
        assert result["status"] == "FILLED"

    def test_query_by_client_order_id_returns_none_on_request_error(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor._client, "request") as mock_request:
            mock_request.side_effect = httpx.RequestError("network failure", request=MagicMock())
            lifecycle = OrderLifecycle(executor._client, executor.api_key, executor.api_secret)
            result = lifecycle.query_by_client_order_id("BTCUSDT", "test-client-id")

        assert result is None

    def test_query_by_client_order_id_returns_none_on_http_error(self, enabled_config):
        executor = LiveExecutor(enabled_config, api_key="test", api_secret="test")
        with patch.object(executor._client, "request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_request.side_effect = httpx.HTTPStatusError(
                "not found", request=MagicMock(), response=mock_response
            )
            lifecycle = OrderLifecycle(executor._client, executor.api_key, executor.api_secret)
            result = lifecycle.query_by_client_order_id("BTCUSDT", "nonexistent-id")

        assert result is None
