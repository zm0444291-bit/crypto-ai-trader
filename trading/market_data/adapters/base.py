"""Abstract base class for market data adapters.

All broker/exchange adapters must implement this interface to ensure
consistent candle data and bid/ask quote retrieval across data sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from trading.market_data.schemas import CandleData


@dataclass(frozen=True)
class BidAskQuote:
    """Snapshot of best bid and ask for a symbol."""

    symbol: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    spread_bps: Decimal
    source: str

    @property
    def mid(self) -> Decimal:
        """Mid price between bid and ask."""
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        """Absolute spread (ask - bid)."""
        return self.ask - self.bid


class MarketDataAdapter(ABC):
    """Abstract interface for fetching market data from any broker/exchange.

    Implementations must handle:
    - Normalized OHLCV candle retrieval (compatible with CandleData schema)
    - Real-time best bid/ask quotes
    - Symbol normalization (e.g., IBKR's XAUUSD vs broker conventions)
    """

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Human-readable name of this adapter (e.g., 'IBKR', 'Pepperstone')."""

    # ── Candle data ───────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        limit: int = 100,
    ) -> list[CandleData]:
        """Fetch historical OHLCV candles for a symbol.

        Args:
            symbol: Normalized symbol name (e.g., "XAUUSD", "EURUSD").
            interval: Candle timeframe.
            limit: Maximum number of candles to retrieve.

        Returns:
            List of CandleData sorted oldest → newest.

        Raises:
            ValueError: If symbol or interval is not supported.
            ConnectionError: If the data source is unreachable.
        """

    # ── Bid/ask quotes ────────────────────────────────────────────────────────

    @abstractmethod
    def get_bid_ask(self, symbol: str) -> BidAskQuote:
        """Get current best bid and ask for a symbol.

        Args:
            symbol: Normalized symbol name.

        Returns:
            BidAskQuote with current bid, ask, spread.

        Raises:
            ValueError: If symbol is not available.
            ConnectionError: If the data source is unreachable.
        """

    # ── Symbol normalization ────────────────────────────────────────────────

    @staticmethod
    @abstractmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """Convert a broker-specific symbol to normalized form.

        For example, IBKR uses "XAUUSD" directly but some brokers
        may use "GOLD" or "XAU/USD". Implementations normalize to
        a canonical form used internally by the trading system.

        Args:
            raw_symbol: Symbol as returned by the broker API.

        Returns:
            Normalized symbol string.
        """

    # ── Health check ────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Return True if the adapter is connected and responsive.

        Default implementation tries to fetch a single candle.
        Override if a lighter check is available.
        """
        try:
            # Try to fetch one candle as health check
            self.fetch_candles(self.default_symbol(), "1m", limit=1)
            return True
        except Exception:
            return False

    @abstractmethod
    def default_symbol(self) -> str:
        """Return the default symbol for this adapter (e.g., 'XAUUSD')."""
