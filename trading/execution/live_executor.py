"""Binance spot live executor skeleton.

This module provides a LiveExecutor that can submit real Binance spot orders.
It is NOT connected to the runtime pipeline by default — the paper path remains
the sole execution route. Enable only after thorough review and testing.

The executor requires live_trading_enabled=true in config/exchanges.yaml and
passes all ExecutionGate checks before any order is sent.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

import httpx

from trading.execution.binance_filters import BinanceFilters

logger = logging.getLogger(__name__)

# Default timeout for Binance API requests: (connect, read) in seconds
_DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 10.0)

# Binance recvWindow: max time difference between request timestamp and server time
_RECV_WINDOW_MS = "5000"


# ---------------------------------------------------------------------------
# Order lifecycle status constants
# ---------------------------------------------------------------------------

class OrderStatus(StrEnum):
    """Canonical order lifecycle states."""
    CREATED = "created"
    SUBMITTED = "submitted"
    ACKED = "acked"                      # order acknowledged, may have partial fill
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"
    PENDING_UNKNOWN = "pending_unknown"  # submit timeout, final state unconfirmed


class ErrorKind(StrEnum):
    """Classified error category returned in ExecutionResult."""
    NONE = "none"
    NETWORK_ERROR = "network_error"       # httpx.RequestError — connection/timeout
    EXCHANGE_HTTP_ERROR = "exchange_http_error"  # httpx.HTTPStatusError — 4xx/5xx
    INTERNAL_ERROR = "internal_error"     # unexpected Exception, logged
    LIVE_TRADING_DISABLED = "live_trading_disabled"
    SYMBOL_NOT_ALLOWED = "symbol_not_allowed"
    FILTER_VALIDATION_FAILED = "filter_validation_failed"
    EXCHANGE_INFO_UNAVAILABLE = "exchange_info_unavailable"
    PENDING_UNKNOWN = "pending_unknown"   # submit timeout, query unconfirmed


# ---------------------------------------------------------------------------
# ExecutionResult — the canonical result type for live execution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionResult:
    """Structured result from a live order submission or query operation.

    Attributes:
        status:     Canonical lifecycle state (one of OrderStatus values).
        code:       Machine-readable error code (one of ErrorKind values) or "ok".
        message:    Human-readable description or error detail.
        client_order_id:  Idempotent client-assigned order ID.
        exchange_order_id: Exchange-assigned order ID (None until known).
        retriable:  True when the operation can be safely retried with same client_order_id.
    """
    status: OrderStatus
    code: str                    # ErrorKind value or "ok"
    message: str
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    retriable: bool = False

    @property
    def success(self) -> bool:
        return self.code == "ok"


# ---------------------------------------------------------------------------
# Legacy OrderResult — retained for backward compatibility during transition
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    """Structured result from a live order submission (legacy)."""
    success: bool
    order_id: str | None
    client_order_id: str | None
    symbol: str
    side: str
    filled_qty: Decimal | None
    filled_price: Decimal | None
    error_message: str | None


# ---------------------------------------------------------------------------
# LiveExecutorConfig
# ---------------------------------------------------------------------------

@dataclass
class LiveExecutorConfig:
    """Configuration for the LiveExecutor."""
    allowed_symbols: list[str]
    live_trading_enabled: bool
    base_url: str = "https://api.binance.com"
    timeout: tuple[float, float] = _DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# OrderLifecycle — query-by-client_order_id helper
# ---------------------------------------------------------------------------

class OrderLifecycle:
    """Encapsulates order-state query logic against Binance.

    Used by LiveExecutor to resolve the final state of an order after a
    submit timeout, preventing the caller from treating an unconfirmed submit
    as a definitive failure.
    """

    def __init__(self, http_client: httpx.Client, api_key: str, api_secret: str) -> None:
        self._client = http_client
        self._api_key = api_key
        self._api_secret = api_secret

    def _sign(self, params: dict[str, str]) -> dict[str, str]:
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**params, "signature": signature}

    def _query_request(self, params: dict[str, str]) -> dict:
        headers = {"X-MBX-APIKEY": self._api_key}
        # Note: we use the base URL from the external client; in tests it is mocked.
        response = self._client.request("GET", "/api/v3/order", headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def query_by_client_order_id(
        self, symbol: str, client_order_id: str
    ) -> dict | None:
        """Query order status by clientOrderId.

        Returns the order dict on success, None on any network or HTTP error.
        """
        try:
            timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
            params = {
                "symbol": symbol,
                "origClientOrderId": client_order_id,
                "timestamp": timestamp,
                "recvWindow": _RECV_WINDOW_MS,
            }
            signed = self._sign(params)
            return self._query_request(signed)
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None

    def exchange_status_to_lifecycle_status(exchange_status: str) -> OrderStatus:
        """Convert Binance order status string to OrderStatus."""
        mapping = {
            "NEW": OrderStatus.ACKED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        return mapping.get(exchange_status, OrderStatus.FAILED)


# ---------------------------------------------------------------------------
# LiveExecutor
# ---------------------------------------------------------------------------

class LiveExecutor:
    """Binance spot live executor with filter validation and idempotent order IDs.

    Does NOT auto-connect to the runtime pipeline. Import and use explicitly
    when ready to enable live execution.

    Caller is responsible for calling `close()` or using as a context manager.
    """

    def __init__(
        self,
        config: LiveExecutorConfig,
        api_key: str,
        api_secret: str,
        filters: BinanceFilters | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not api_secret or not api_secret.strip():
            raise ValueError("api_secret must be non-empty")
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret
        self.filters = filters or BinanceFilters()
        self._client = httpx.Client(base_url=config.base_url, timeout=config.timeout)
        self._exchange_info_fetched = False

    def __enter__(self) -> LiveExecutor:
        return self

    def __exit__(self, *args: object) -> None:
        self._client.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def ensure_exchange_info(self, symbols: list[str] | None = None) -> None:
        """Fetch and cache exchangeInfo if not already done."""
        if not self._exchange_info_fetched:
            self.filters.fetch_and_cache(symbols=symbols or self.config.allowed_symbols)
            self._exchange_info_fetched = True

    def generate_client_order_id(
        self,
        strategy_name: str,
        cycle_id: str,
        symbol: str,
        attempt: int = 1,
    ) -> str:
        """Generate an idempotent clientOrderId.

        Format: {strategy}-{cycle}-{symbol}-{attempt}
        The attempt field allows retry with a new ID while staying idempotent-aware.
        """
        return f"{strategy_name}-{cycle_id}-{symbol}-{attempt}"

    def _sign_request(self, params: dict[str, str]) -> dict[str, str]:
        """Sign Binance API request with HMAC SHA256."""
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**params, "signature": signature}

    def _request(self, method: str, endpoint: str, params: dict[str, str] | None = None) -> dict:
        """Make an authenticated Binance API request.

        Raises:
            httpx.HTTPStatusError: On HTTP 4xx/5xx responses.
            httpx.RequestError: On network/connection errors.
        """
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.config.base_url}{endpoint}"
        signed_params = self._sign_request(params) if params else None
        if method.upper() == "GET":
            response = self._client.request(method, url, headers=headers, params=signed_params)
        else:
            response = self._client.request(method, url, headers=headers, data=signed_params)
        response.raise_for_status()
        return response.json()

    def _apply_filters(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
    ) -> tuple[Decimal, Decimal] | tuple[None, None]:
        """Apply LOT_SIZE, PRICE_FILTER, and minNotional validation.

        Returns (formatted_qty, formatted_price) or (None, None) if invalid.
        """
        formatted_qty = self.filters.format_quantity(symbol, qty)
        formatted_price = self.filters.format_price(symbol, price)
        if formatted_qty is None or formatted_price is None:
            return None, None

        if not self.filters.validate_min_notional(symbol, formatted_qty, formatted_price):
            return None, None

        return formatted_qty, formatted_price

    def _build_market_order_params(
        self,
        symbol: str,
        side: str,
        formatted_qty: Decimal,
        client_order_id: str,
    ) -> dict[str, str]:
        """Build signed params for a MARKET order."""
        timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
        return {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(formatted_qty),
            "newClientOrderId": client_order_id,
            "timestamp": timestamp,
            "recvWindow": _RECV_WINDOW_MS,
        }

    def _submit_order(
        self,
        symbol: str,
        side: str,
        formatted_qty: Decimal,
        formatted_price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> ExecutionResult:
        """Attempt to submit a market order. Returns ExecutionResult with final state.

        On RequestError (timeout/connection failure) this method does NOT fall back
        to query — the caller (_place_market_order) is responsible for that decision.
        """
        client_order_id = self.generate_client_order_id(
            strategy_name=strategy_name,
            cycle_id=cycle_id,
            symbol=symbol,
            attempt=1,
        )

        params = self._build_market_order_params(
            symbol, side, formatted_qty, client_order_id
        )

        try:
            result = self._request("POST", "/api/v3/order", params)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            # 429 (rate limit) and 5xx are transient — retriable
            retriable = code >= 429
            return ExecutionResult(
                status=OrderStatus.REJECTED,
                code=ErrorKind.EXCHANGE_HTTP_ERROR.value,
                message=f"exchange_http_error:{code}",
                client_order_id=client_order_id,
                retriable=retriable,
            )
        except httpx.RequestError as e:
            return ExecutionResult(
                status=OrderStatus.PENDING_UNKNOWN,
                code=ErrorKind.NETWORK_ERROR.value,
                message=f"network_error:{type(e).__name__}",
                client_order_id=client_order_id,
                retriable=True,
            )
        except Exception:
            logger.exception(
                "Unexpected exception while placing live market order",
                extra={
                    "symbol": symbol,
                    "side": side,
                    "strategy_name": strategy_name,
                    "cycle_id": cycle_id,
                },
            )
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.INTERNAL_ERROR.value,
                message="internal_error",
                client_order_id=client_order_id,
                retriable=False,
            )

        # Success — derive fills
        fills = result.get("fills", [])
        exchange_order_id = str(result.get("orderId", ""))
        filled_qty: Decimal | None = None

        if fills:
            filled_qty = sum(Decimal(f["qty"]) for f in fills)

        # Determine terminal status
        order_status_str = result.get("status", "")
        lifecycle_status = OrderLifecycle.exchange_status_to_lifecycle_status(order_status_str)

        return ExecutionResult(
            status=lifecycle_status,
            code="ok",
            message="order_filled" if filled_qty else "order_acked",
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            retriable=False,
        )

    def _resolve_pending_unknown(
        self,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionResult:
        """Query Binance for the final state of a timed-out order.

        If the order is found, returns its true terminal state.
        If the query also fails, returns pending_unknown with retriable=True.
        """
        timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
        params = {
            "symbol": symbol,
            "origClientOrderId": client_order_id,
            "timestamp": timestamp,
            "recvWindow": _RECV_WINDOW_MS,
        }
        try:
            order_data = self._request("GET", "/api/v3/order", params)
        except httpx.HTTPStatusError as e:
            # HTTP error on query — Binance responded definitively (e.g., 429 rate limit)
            return ExecutionResult(
                status=OrderStatus.PENDING_UNKNOWN,
                code=ErrorKind.EXCHANGE_HTTP_ERROR.value,
                message=f"query_failed:http_{e.response.status_code}",
                client_order_id=client_order_id,
                retriable=True,
            )
        except httpx.RequestError:
            # Network/timeout on query — unknown whether Binance received the order
            return ExecutionResult(
                status=OrderStatus.PENDING_UNKNOWN,
                code=ErrorKind.PENDING_UNKNOWN.value,
                message="submit_timeout_query_failed:order_not_found_or_unavailable",
                client_order_id=client_order_id,
                retriable=True,
            )

        exchange_status = order_data.get("status", "")
        lifecycle_status = OrderLifecycle.exchange_status_to_lifecycle_status(exchange_status)
        exchange_order_id = str(order_data.get("orderId", ""))

        return ExecutionResult(
            status=lifecycle_status,
            code="ok",
            message=f"confirmed_via_query:{exchange_status}",
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            retriable=False,
        )

    def _place_market_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> ExecutionResult:
        """Core order placement logic returning ExecutionResult with full lifecycle info."""
        # --- preconditions ---
        if not self.config.live_trading_enabled:
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.LIVE_TRADING_DISABLED.value,
                message="live_trading_disabled",
                retriable=False,
            )

        if symbol not in self.config.allowed_symbols:
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.SYMBOL_NOT_ALLOWED.value,
                message=f"symbol_not_allowed:{symbol}",
                retriable=False,
            )

        # --- fetch exchange info ---
        try:
            self.ensure_exchange_info()
        except httpx.HTTPStatusError as exc:
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.EXCHANGE_INFO_UNAVAILABLE.value,
                message=f"exchange_info_unavailable:http_{exc.response.status_code}",
                retriable=True,
            )
        except httpx.RequestError as exc:
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.EXCHANGE_INFO_UNAVAILABLE.value,
                message=f"exchange_info_unavailable:network_error:{type(exc).__name__}",
                retriable=True,
            )

        # --- filter validation ---
        formatted_qty, formatted_price = self._apply_filters(symbol, qty, price)
        if formatted_qty is None or formatted_price is None:
            return ExecutionResult(
                status=OrderStatus.FAILED,
                code=ErrorKind.FILTER_VALIDATION_FAILED.value,
                message="filter_validation_failed",
                retriable=False,
            )

        # --- submit ---
        submit_result = self._submit_order(
            symbol=symbol,
            side=side,
            formatted_qty=formatted_qty,
            formatted_price=formatted_price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )

        # If submit returned PENDING_UNKNOWN (network error on submit),
        # resolve via query-by-client_order_id
        if submit_result.status == OrderStatus.PENDING_UNKNOWN:
            resolved = self._resolve_pending_unknown(symbol, submit_result.client_order_id)
            # Carry over client_order_id since resolved result may not have it
            return ExecutionResult(
                status=resolved.status,
                code=resolved.code,
                message=resolved.message,
                client_order_id=submit_result.client_order_id,
                exchange_order_id=resolved.exchange_order_id,
                retriable=resolved.retriable,
            )

        return submit_result

    def place_market_buy(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> OrderResult:
        """Place a market buy order on Binance spot.

        Args:
            symbol: Trading symbol, e.g. "BTCUSDT".
            qty: Raw quantity (will be filtered/floored to stepSize).
            price: Reference price for minNotional check.
            strategy_name: Strategy identifier (included in clientOrderId).
            cycle_id: Cycle identifier (included in clientOrderId).

        Returns:
            OrderResult (legacy) for backward compatibility.
            Prefer execute_market_order() which returns ExecutionResult.
        """
        result = self._place_market_order(
            symbol=symbol,
            side="BUY",
            qty=qty,
            price=price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )
        return self._to_order_result(result, symbol, "BUY")

    def place_market_sell(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> OrderResult:
        """Place a market sell order on Binance spot.

        Args:
            symbol: Trading symbol, e.g. "BTCUSDT".
            qty: Raw quantity (will be filtered/floored to stepSize).
            price: Reference price for minNotional check.
            strategy_name: Strategy identifier (included in clientOrderId).
            cycle_id: Cycle identifier (included in clientOrderId).

        Returns:
            OrderResult (legacy) for backward compatibility.
            Prefer execute_market_order() which returns ExecutionResult.
        """
        result = self._place_market_order(
            symbol=symbol,
            side="SELL",
            qty=qty,
            price=price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )
        return self._to_order_result(result, symbol, "SELL")

    def execute_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: Decimal,
        price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> ExecutionResult:
        """Place a market order and return full ExecutionResult with lifecycle info.

        This is the preferred entry point for new code. place_market_buy/place_market_sell
        are retained for backward compatibility but delegate to this method.
        """
        return self._place_market_order(
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )

    def _to_order_result(self, exec_result: ExecutionResult, symbol: str, side: str) -> OrderResult:
        """Convert ExecutionResult to legacy OrderResult for backward compatibility."""
        return OrderResult(
            success=exec_result.success,
            order_id=exec_result.exchange_order_id,
            client_order_id=exec_result.client_order_id,
            symbol=symbol,
            side=side,
            filled_qty=None,  # not tracked in ExecutionResult path
            filled_price=None,
            error_message=exec_result.message if not exec_result.success else None,
        )

    def get_order_status(self, symbol: str, order_id: str) -> dict | None:
        """Query order status from Binance by exchange order ID.

        Returns None on any error (network, HTTP, etc.).
        """
        try:
            timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
            params = {
                "symbol": symbol,
                "orderId": order_id,
                "timestamp": timestamp,
                "recvWindow": _RECV_WINDOW_MS,
            }
            return self._request("GET", "/api/v3/order", params)
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None
