"""Binance spot order filter validation and formatting.

Caches exchangeInfo from Binance to validate and format quantity/price
values against symbol-specific LOT_SIZE, PRICE_FILTER (tickSize), and
MIN_NOTIONAL constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

import httpx

_DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 10.0)


@dataclass
class SymbolFilters:
    """Parsed Binance symbol filter constraints."""

    min_notional: Decimal
    step_size: Decimal
    tick_size: Decimal

    @classmethod
    def from_binance(cls, filters: list[dict[str, Any]]) -> SymbolFilters:
        """Parse LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL from Binance filter list."""
        min_notional = Decimal("0")
        step_size = Decimal("1")
        tick_size = Decimal("0.00000001")

        for f in filters:
            if f["filterType"] == "MIN_NOTIONAL":
                min_notional = Decimal(f["minNotional"])
            elif f["filterType"] == "LOT_SIZE":
                step_size = Decimal(f["stepSize"])
            elif f["filterType"] == "PRICE_FILTER":
                tick_size = Decimal(f["tickSize"])

        return cls(min_notional=min_notional, step_size=step_size, tick_size=tick_size)


@dataclass
class BinanceFilters:
    """Cache of Binance symbol filters — not thread-safe, single-threaded use only."""

    _filters: dict[str, SymbolFilters] = field(default_factory=dict)
    _client: httpx.Client | None = None

    def fetch_and_cache(self, symbols: list[str] | None = None) -> None:
        """Fetch exchangeInfo from Binance and cache symbol filters.

        Args:
            symbols: If provided, only filters for these symbols are stored.
                     If None, all symbols are cached.
        """
        base = "https://api.binance.com"
        client = self._client or httpx.Client(base_url=base, timeout=_DEFAULT_TIMEOUT)
        try:
            response = client.get("/api/v3/exchangeInfo")
            response.raise_for_status()
        finally:
            if self._client is None:
                client.close()

        data = response.json()
        for symbol_info in data.get("symbols", []):
            sym = symbol_info.get("symbol", "")
            if symbols is not None and sym not in symbols:
                continue
            if symbol_info.get("status") != "TRADING":
                continue
            self._filters[sym] = SymbolFilters.from_binance(
                symbol_info.get("filters", [])
            )

    def get_filters(self, symbol: str) -> SymbolFilters | None:
        """Return cached filters for symbol, or None if not yet fetched."""
        return self._filters.get(symbol)

    def format_quantity(self, symbol: str, qty: Decimal) -> Decimal | None:
        """Floor quantity to stepSize for symbol.

        Returns None if symbol is not cached.
        """
        filters = self._filters.get(symbol)
        if filters is None:
            return None
        # Quantize to stepSize precision
        q = qty.quantize(filters.step_size, rounding=ROUND_DOWN)
        if q <= Decimal("0"):
            return None
        return q

    def format_price(self, symbol: str, price: Decimal) -> Decimal | None:
        """Round price to tickSize for symbol.

        Returns None if symbol is not cached.
        """
        filters = self._filters.get(symbol)
        if filters is None:
            return None
        return price.quantize(filters.tick_size, rounding=ROUND_DOWN)

    def validate_min_notional(self, symbol: str, qty: Decimal, price: Decimal) -> bool:
        """Check whether qty * price meets MIN_NOTIONAL for symbol.

        Returns False if symbol is not cached.
        """
        filters = self._filters.get(symbol)
        if filters is None:
            return False
        # Quantize qty to stepSize and price to tickSize before multiplying
        qty_q = qty.quantize(filters.step_size, rounding=ROUND_DOWN)
        price_q = price.quantize(filters.tick_size, rounding=ROUND_DOWN)
        return qty_q * price_q >= filters.min_notional


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Floor a decimal value to the nearest step interval."""
    return value.quantize(step, rounding=ROUND_DOWN)


def round_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Round a decimal value to the nearest tick interval."""
    return value.quantize(tick, rounding=ROUND_DOWN)