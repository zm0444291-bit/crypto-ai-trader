"""Pepperstone REST API market data adapter.

Fetches historical candle data and real-time bid/ask quotes from Pepperstone,
a forex and commodities broker. Falls back to a mock implementation when the
REST API is unreachable or credentials are unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

import requests

from trading.market_data.adapters.base import BidAskQuote, MarketDataAdapter
from trading.market_data.schemas import CandleData

logger = logging.getLogger(__name__)

# Pepperstone REST API base URL (IC Markets compatible API)
_PEPPERSTONE_REST_BASE = "https://api.pepperstone.jp/v1"

# Map internal timeframe strings to Pepperstone API granularity
_PEPPERSTONE_GRANULARITY_MAP: dict[str, str] = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
}

# Supported timeframes
_SUPPORTED_INTERVALS: set[str] = set(_PEPPERSTONE_GRANULARITY_MAP)

# Minutes per interval for close_time calculation
_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Mock implementation (used when Pepperstone API is unavailable)
# ─────────────────────────────────────────────────────────────────────────────


class MockPepperstoneAdapter(MarketDataAdapter):
    """Mock adapter that returns synthetic forex data.

    Used when Pepperstone credentials are not configured or the API is unreachable.
    """

    def __init__(
        self,
        *,
        symbol: str = "XAUUSD",
        mock_bid: Decimal = Decimal("2345.50"),
        mock_ask: Decimal = Decimal("2345.80"),
        mock_candle_close: Decimal = Decimal("2345.65"),
    ) -> None:
        self._symbol = symbol
        self._bid = mock_bid
        self._ask = mock_ask
        self._close = mock_candle_close

    @property
    def adapter_name(self) -> str:
        return "Pepperstone (Mock)"

    def default_symbol(self) -> str:
        return self._symbol

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """Normalize Pepperstone symbol to internal form.

        Pepperstone symbols may come as "XAUUSD.pro" or "XAUUSD.m" or "XAUUSD".
        We strip the suffix and normalise to a 6-character base/quote pair.
        """
        cleaned = raw_symbol.upper().replace("/", "").replace("-", "")
        # Strip Pepperstone suffixes like .pro, .m, .tick
        for suffix in (".PRO", ".M", ".TICK"):
            if suffix in cleaned:
                cleaned = cleaned.replace(suffix, "")
        # Map known aliases
        symbol_map = {
            "XAUXAU": "XAUUSD",
            "GOLD": "XAUUSD",
            "XAUUSD": "XAUUSD",
            "EURUSD": "EURUSD",
            "GBPUSD": "GBPUSD",
            "USDJPY": "USDJPY",
            "AUDUSD": "AUDUSD",
            "NZDUSD": "NZDUSD",
            "USDCAD": "USDCAD",
            "USDCHF": "USDCHF",
        }
        return symbol_map.get(cleaned, cleaned)

    def fetch_candles(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        limit: int = 100,
    ) -> list[CandleData]:
        if interval not in _SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval!r}")
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        timeframe_delta = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "1d": timedelta(days=1),
        }[interval]
        candles = []
        for i in range(limit, 0, -1):
            open_time = now - timeframe_delta * i
            close_time = open_time + timeframe_delta
            # Add tiny variation so candles aren't identical
            variation = Decimal(str((i % 5) * 0.05))
            # Ensure high >= close and low <= open
            high = self._close + Decimal("0.10") + variation
            low = self._close - Decimal("0.10") - variation
            open_price = self._close - Decimal("0.05")
            close_price = self._close + Decimal("0.05")
            candles.append(
                CandleData(
                    symbol=self._symbol,
                    timeframe=interval,
                    open_time=open_time,
                    close_time=close_time,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=Decimal("1000") + Decimal(str(i * 10)),
                    source="pepperstone_mock",
                )
            )
        return candles

    def get_bid_ask(self, symbol: str) -> BidAskQuote:
        spread = self._ask - self._bid
        spread_bps = (
            (spread / self._bid * Decimal("10000")).quantize(Decimal("0.01"))
            if self._bid
            else Decimal("0")
        )
        return BidAskQuote(
            symbol=self._symbol,
            timestamp=datetime.now(UTC),
            bid=self._bid,
            ask=self._ask,
            spread_bps=spread_bps,
            source="pepperstone_mock",
        )

    def health_check(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Live Pepperstone REST adapter
# ─────────────────────────────────────────────────────────────────────────────


class PepperstoneAdapter(MarketDataAdapter):
    """Live adapter connecting to Pepperstone REST API.

    Pepperstone uses an IC Markets-compatible API. Authentication requires
    an API key and secret. The API provides forex and commodities pricing.

    Parameters
    ----------
    api_key : str
        Pepperstone API key (from Pepperstone client portal).
    api_secret : str
        Pepperstone API secret.
    base_url : str
        REST API base URL (default: https://api.pepperstone.jp/v1).
    timeout : int
        HTTP request timeout in seconds (default: 15).

    Raises
    ------
    RuntimeError
        If the `requests` library is not installed or credentials are missing.
    ConnectionError
        If the API is unreachable.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = _PEPPERSTONE_REST_BASE,
        timeout: int = 15,
    ) -> None:
        if requests is None:
            raise RuntimeError(
                "requests is not installed. Install with: pip install requests"
            )
        if not api_key or not api_secret:
            raise RuntimeError(
                "Pepperstone api_key and api_secret are required for live trading."
            )
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
        })

    def _sign_request(self, params: dict[str, str]) -> str:
        """Generate HMAC-SHA256 signature for Pepperstone API authentication."""
        # Pepperstone uses nonce-based auth: nonce = timestamp in milliseconds
        nonce = str(int(time.time() * 1000))
        message = nonce + self._api_key
        signature = hmac.new(
            self._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _get_auth_headers(self) -> dict[str, str]:
        """Return authentication headers with HMAC signature."""
        nonce = str(int(time.time() * 1000))
        message = nonce + self._api_key
        signature = hmac.new(
            self._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-Key": self._api_key,
            "X-AUTH-Signature": signature,
            "X-AUTH-Nonce": nonce,
        }

    def _request(
        self, method: str, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make an authenticated request to the Pepperstone REST API."""
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        headers = self._get_auth_headers()
        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                params=params or {},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return dict(response.json())
        except requests.RequestException as exc:
            raise ConnectionError(
                f"Pepperstone API request failed ({method} {url}): {exc}"
            ) from exc

    # ── MarketDataAdapter interface ──────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "Pepperstone"

    def default_symbol(self) -> str:
        return "XAUUSD"

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """Normalize Pepperstone symbol to internal form.

        Pepperstone symbols may include suffixes like ".pro", ".m", ".tick".
        We strip these and map known aliases to canonical pairs.
        """
        cleaned = raw_symbol.upper().replace("/", "").replace("-", "")
        for suffix in (".PRO", ".M", ".TICK"):
            if suffix in cleaned:
                cleaned = cleaned.replace(suffix, "")
        symbol_map = {
            "XAUXAU": "XAUUSD",
            "GOLD": "XAUUSD",
            "XAUUSD": "XAUUSD",
            "EURUSD": "EURUSD",
            "GBPUSD": "GBPUSD",
            "USDJPY": "USDJPY",
            "AUDUSD": "AUDUSD",
            "NZDUSD": "NZDUSD",
            "USDCAD": "USDCAD",
            "USDCHF": "USDCHF",
        }
        return symbol_map.get(cleaned, cleaned)

    def _to_pepperstone_symbol(self, symbol: str) -> str:
        """Convert internal symbol to Pepperstone API symbol format."""
        return symbol + ".pro"

    def fetch_candles(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        limit: int = 100,
    ) -> list[CandleData]:
        if interval not in _SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval!r}")
        normalized = self.normalize_symbol(symbol)
        ps_symbol = self._to_pepperstone_symbol(normalized)
        granularity = _PEPPERSTONE_GRANULARITY_MAP[interval]
        # Pepperstone API: /candles?symbol=XAUUSD.pro&granularity=H1&count=100
        data = self._request(
            "GET",
            "/candles",
            params={
                "symbol": ps_symbol,
                "granularity": granularity,
                "count": str(limit),
            },
        )
        candles_raw = data.get("candles", [])
        if not candles_raw:
            raise ConnectionError(f"No historical data returned for {symbol}")
        minutes = _INTERVAL_MINUTES[interval]
        return [
            CandleData(
                symbol=normalized,
                timeframe=interval,
                open_time=datetime.fromisoformat(c["time"].replace("Z", "+00:00")),
                close_time=datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
                + timedelta(minutes=minutes),
                open=Decimal(str(c["bid"]["o"])),
                high=Decimal(str(c["bid"]["h"])),
                low=Decimal(str(c["bid"]["l"])),
                close=Decimal(str(c["bid"]["c"])),
                volume=Decimal(str(c.get("volume", 0))),
                source="pepperstone",
            )
            for c in candles_raw[-limit:]
        ]

    def get_bid_ask(self, symbol: str) -> BidAskQuote:
        normalized = self.normalize_symbol(symbol)
        ps_symbol = self._to_pepperstone_symbol(normalized)
        # Pepperstone API: /ticks?symbol=XAUUSD.pro&fields=bid,ask
        data = self._request(
            "GET",
            "/ticks",
            params={
                "symbol": ps_symbol,
                "fields": "bid,ask",
            },
        )
        tick = data.get("tick", data)
        bid = Decimal(str(tick["bid"]))
        ask = Decimal(str(tick["ask"]))
        spread = ask - bid
        spread_bps = (
            (spread / bid * Decimal("10000")).quantize(Decimal("0.01"))
            if bid
            else Decimal("0")
        )
        return BidAskQuote(
            symbol=normalized,
            timestamp=datetime.now(UTC),
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            source="pepperstone",
        )

    def health_check(self) -> bool:
        try:
            self.fetch_candles("XAUUSD", "1m", limit=1)
            return True
        except Exception as exc:
            logger.warning("Pepperstone health check failed: %s", exc)
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Factory that auto-falls back to mock
# ─────────────────────────────────────────────────────────────────────────────


def create_pepperstone_adapter(
    *, use_mock: bool = False, **kwargs: Any
) -> MarketDataAdapter:
    """Create a Pepperstone adapter.

    By default (use_mock=False), the function attempts to connect to the live
    Pepperstone REST API. If the connection fails or credentials are missing,
    a mock adapter is returned instead. Set use_mock=True to force the mock
    regardless of connectivity.

    Parameters
    ----------
    use_mock : bool
        If True, always return a MockPepperstoneAdapter.
    **kwargs
        Forwarded to PepperstoneAdapter (api_key, api_secret, base_url, timeout).

    Returns
    -------
    MarketDataAdapter
        Either a live PepperstoneAdapter or MockPepperstoneAdapter.
    """
    if use_mock:
        return MockPepperstoneAdapter()
    if not kwargs.get("api_key") or not kwargs.get("api_secret"):
        logger.warning(
            "Pepperstone API credentials not provided; using mock adapter."
        )
        return MockPepperstoneAdapter()
    adapter = PepperstoneAdapter(**kwargs)
    try:
        if not adapter.health_check():
            raise ConnectionError("Pepperstone health check returned False.")
        return adapter
    except Exception as exc:
        logger.warning(
            "Could not connect to Pepperstone (%s). Falling back to mock adapter.",
            exc,
        )
        return MockPepperstoneAdapter()
