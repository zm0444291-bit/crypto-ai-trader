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

import httpx

from trading.execution.binance_filters import BinanceFilters

logger = logging.getLogger(__name__)

# Default timeout for Binance API requests: (connect, read) in seconds
_DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 10.0)

# Binance recvWindow: max time difference between request timestamp and server time
_RECV_WINDOW_MS = "5000"


@dataclass
class OrderResult:
    """Structured result from a live order submission."""

    success: bool
    order_id: str | None
    client_order_id: str | None
    symbol: str
    side: str
    filled_qty: Decimal | None
    filled_price: Decimal | None
    error_message: str | None


@dataclass
class LiveExecutorConfig:
    """Configuration for the LiveExecutor."""

    allowed_symbols: list[str]
    live_trading_enabled: bool
    base_url: str = "https://api.binance.com"
    timeout: tuple[float, float] = _DEFAULT_TIMEOUT


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

    def _place_market_order(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal,
        strategy_name: str,
        cycle_id: str,
    ) -> OrderResult:
        """Shared implementation for market buy and sell."""
        if not self.config.live_trading_enabled:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=None,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message="live_trading_disabled",
            )

        if symbol not in self.config.allowed_symbols:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=None,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message=f"symbol_not_allowed:{symbol}",
            )

        try:
            self.ensure_exchange_info()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=None,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message=f"exchange_info_unavailable:{type(exc).__name__}",
            )

        formatted_qty, formatted_price = self._apply_filters(symbol, qty, price)
        if formatted_qty is None or formatted_price is None:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=None,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message="filter_validation_failed",
            )

        client_order_id = self.generate_client_order_id(
            strategy_name=strategy_name,
            cycle_id=cycle_id,
            symbol=symbol,
            attempt=1,
        )

        timestamp = str(int(datetime.now(UTC).timestamp() * 1000))
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(formatted_qty),
            "newClientOrderId": client_order_id,
            "timestamp": timestamp,
            "recvWindow": _RECV_WINDOW_MS,
        }

        try:
            result = self._request("POST", "/api/v3/order", params)

            fills = result.get("fills", [])
            filled_qty = Decimal("0")
            filled_price = Decimal("0")
            if fills:
                total_qty = sum(Decimal(f["qty"]) for f in fills)
                total_cost = sum(Decimal(f["price"]) * Decimal(f["qty"]) for f in fills)
                if total_qty > 0:
                    filled_price = (total_cost / total_qty).quantize(formatted_price)
                filled_qty = total_qty

            return OrderResult(
                success=True,
                order_id=str(result.get("orderId", "")),
                client_order_id=result.get("clientOrderId", client_order_id),
                symbol=symbol,
                side=side,
                filled_qty=filled_qty,
                filled_price=filled_price,
                error_message=None,
            )
        except httpx.HTTPStatusError as e:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message=f"http_error:{e.response.status_code}",
            )
        except httpx.RequestError as e:
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message=f"request_error:{type(e).__name__}",
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
            return OrderResult(
                success=False,
                order_id=None,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                filled_qty=None,
                filled_price=None,
                error_message="internal_error",
            )

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
            OrderResult with success status and order details or error message.
        """
        return self._place_market_order(
            symbol=symbol,
            side="BUY",
            qty=qty,
            price=price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )

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
            OrderResult with success status and order details or error message.
        """
        return self._place_market_order(
            symbol=symbol,
            side="SELL",
            qty=qty,
            price=price,
            strategy_name=strategy_name,
            cycle_id=cycle_id,
        )

    def get_order_status(self, symbol: str, order_id: str) -> dict | None:
        """Query order status from Binance.

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
