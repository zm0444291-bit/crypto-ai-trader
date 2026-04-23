"""IBKR market data adapter using ib_insync.

Fetches XAUUSD (Gold) real-time and historical data from Interactive Brokers
via their Trader Workstation (TWS) API. Falls back to a mock implementation
when the IBKR connection is unavailable or ib_insync is not installed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from trading.market_data.adapters.base import BidAskQuote, MarketDataAdapter
from trading.market_data.schemas import CandleData

logger = logging.getLogger(__name__)

# Attempt to import ib_insync; if not available the module still loads
# but live IBKR functionality is disabled.
try:
    from ib_insync import TWS, Contract, Forex  # type: ignore[import-not-found]
except ImportError:
    Contract = None
    Forex = None
    TWS = None
    IB_IS_AVAILABLE = False
else:
    IB_IS_AVAILABLE = True

if TYPE_CHECKING:
    from ib_insync import IB

# IBKR contract identifiers for XAUUSD (CASH pair, not futures)
_XAUUSD_CONTRACT_SPEC = {
    "symbol": "XAU",
    "currency": "USD",
    "secType": "CASH",
    "exchange": "IDEALPRO",
}

# Map internal timeframe strings to ib_insync bar sizes
_IBKR_BAR_SIZE_MAP: dict[str, str] = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "30m": "30 mins",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}

# Supported timeframes
_SUPPORTED_INTERVALS: set[str] = set(_IBKR_BAR_SIZE_MAP)

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


def _ibkr_contract(symbol: str) -> Contract:
    """Return the appropriate ib_insync Contract for a normalized symbol."""
    if not IB_IS_AVAILABLE:
        raise RuntimeError("ib_insync is not installed; cannot create contract")
    if symbol.upper() == "XAUUSD":
        c = Contract()
        c.symbol = "XAU"
        c.currency = "USD"
        c.secType = "CASH"
        c.exchange = "IDEALPRO"
        return c
    # Generic forex pair fallback (e.g. EURUSD)
    base, quote = symbol[:3], symbol[3:]
    c = Forex(f"{base}{quote}")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# Mock implementation (used when IBKR is unavailable)
# ─────────────────────────────────────────────────────────────────────────────


class MockIBKRAdapter(MarketDataAdapter):
    """Mock adapter that returns synthetic XAUUSD data.

    Used when TWS/Gateway is not running or ib_insync is unavailable.
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
        return "IBKR (Mock)"

    def default_symbol(self) -> str:
        return self._symbol

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        cleaned = raw_symbol.upper().replace("/", "").replace("-", "")
        if cleaned in ("XAUXAU", "XAUUSD"):
            return "XAUUSD"
        if len(cleaned) == 6:
            return cleaned  # Assume base/quote order already correct
        return raw_symbol.upper()

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
                    source="ibkr_mock",
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
            source="ibkr_mock",
        )

    def health_check(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Live IBKR adapter
# ─────────────────────────────────────────────────────────────────────────────


class IBKRAdapter(MarketDataAdapter):
    """Live adapter connecting to IBKR TWS/Gateway via ib_insync.

    Parameters
    ----------
    host : str
        TWS/Gateway host (default: 127.0.0.1).
    port : int
        TWS socket port (default: 7497 for live, 7496 for paper).
    client_id : int
        Unique client ID for this connection (default: 99).
    timeout : int
        Connection timeout in seconds (default: 15).

    Raises
    ------
    RuntimeError
        If ib_insync is not installed.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 99,
        timeout: int = 15,
    ) -> None:
        if not IB_IS_AVAILABLE:
            raise RuntimeError(
                "ib_insync is not installed. Install with: pip install ib_insync"
            )
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._ib: IB = TWS()
        self._connected = False

    # ── Connection lifecycle ───────────────────────────────────────────────────

    def _ensure_connected(self) -> None:
        """Connect to TWS if not already connected."""
        if self._connected and self._ib.isConnected():
            return
        try:
            self._ib.connect(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=self._timeout,
            )
            self._connected = True
            logger.info(
                "Connected to IBKR at %s:%d (client_id=%d)",
                self._host,
                self._port,
                self._client_id,
            )
        except Exception as exc:
            self._connected = False
            raise ConnectionError(f"Failed to connect to IBKR: {exc}") from exc

    def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._connected and self._ib.isConnected():
            self._ib.disconnect()
        self._connected = False
        logger.info("Disconnected from IBKR.")

    # ── MarketDataAdapter interface ──────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "IBKR"

    def default_symbol(self) -> str:
        return "XAUUSD"

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """Normalize IBKR symbol to internal form.

        IBKR returns XAUUSD directly for the IDEALPRO cash pair.
        Other forex pairs are returned as BASE/QUOTE (e.g. EURUSD).
        """
        cleaned = raw_symbol.upper().replace("/", "").replace("-", "")
        if cleaned in ("XAUXAU", "XAUUSD"):
            return "XAUUSD"
        # Assume 6-character base/quote pair
        if len(cleaned) == 6:
            return cleaned
        return raw_symbol.upper()

    def fetch_candles(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        limit: int = 100,
    ) -> list[CandleData]:
        if interval not in _SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval!r}")
        self._ensure_connected()
        contract = _ibkr_contract(symbol)
        bar_size = _IBKR_BAR_SIZE_MAP[interval]
        # endDateTime='' means most recent bars
        bars = self._ib.reqHistoricalData(
            contract=contract,
            endDateTime="",
            durationStr=f"{limit} S",
            barSizeSetting=bar_size,
            whatToShow="MIDPOINT",
            useRTH=True,
            formatDate=2,  # UTC datetime strings
            keepUpToDate=False,
        )
        if not bars:
            raise ConnectionError(f"No historical data returned for {symbol}")
        minutes = _INTERVAL_MINUTES[interval]
        return [
            CandleData(
                symbol=self.normalize_symbol(symbol),
                timeframe=interval,
                open_time=bar.date,
                close_time=bar.date + timedelta(minutes=minutes),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=Decimal(str(bar.volume)),
                source="ibkr",
            )
            for bar in bars[-limit:]
        ]

    def get_bid_ask(self, symbol: str) -> BidAskQuote:
        self._ensure_connected()
        contract = _ibkr_contract(symbol)
        [tick] = self._ib.reqTickByTickData(
            contract=contract, tickType="BidAsk", numberOfTicks=1
        )
        bid = Decimal(str(tick.bidPrice))
        ask = Decimal(str(tick.askPrice))
        spread = ask - bid
        spread_bps = (
            (spread / bid * Decimal("10000")).quantize(Decimal("0.01"))
            if bid
            else Decimal("0")
        )
        return BidAskQuote(
            symbol=self.normalize_symbol(symbol),
            timestamp=datetime.now(UTC),
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            source="ibkr",
        )

    def health_check(self) -> bool:
        try:
            self._ensure_connected()
            self.fetch_candles("XAUUSD", "1m", limit=1)
            return True
        except Exception as exc:
            logger.warning("IBKR health check failed: %s", exc)
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Factory that auto-falls back to mock
# ─────────────────────────────────────────────────────────────────────────────


def create_ibkr_adapter(*, use_mock: bool = False, **kwargs: Any) -> MarketDataAdapter:
    """Create an IBKR adapter.

    By default (use_mock=False), the function attempts to connect to a live
    TWS/Gateway. If the connection fails, a mock adapter is returned instead.
    Set use_mock=True to force the mock regardless of connectivity.

    Parameters
    ----------
    use_mock : bool
        If True, always return a MockIBKRAdapter.
    **kwargs
        Forwarded to IBKRAdapter (host, port, client_id, timeout).

    Returns
    -------
    MarketDataAdapter
        Either a live IBKRAdapter or MockIBKRAdapter.
    """
    if use_mock:
        return MockIBKRAdapter()
    if not IB_IS_AVAILABLE:
        logger.warning("ib_insync not installed; using mock adapter.")
        return MockIBKRAdapter()
    adapter = IBKRAdapter(**kwargs)
    try:
        adapter._ensure_connected()
        return adapter
    except Exception as exc:
        logger.warning(
            "Could not connect to IBKR (%s). Falling back to mock adapter.", exc
        )
        return MockIBKRAdapter()
