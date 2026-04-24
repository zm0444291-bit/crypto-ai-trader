"""Paper executor with tiered slippage simulation.

Slippage is configured per-symbol in config/execution.yaml (slippage_tiers).
Each tier is in basis points (bps). slippage = quantity * tier_bps / 10000
"""

import warnings
from datetime import datetime
from decimal import Decimal
from typing import Literal, overload

from pydantic import BaseModel

from trading.market_data.adapters.base import BidAskQuote
from trading.risk.position_sizing import PositionSizeResult
from trading.strategies.base import TradeCandidate

# Slippage tiers in basis points (bps), keyed by symbol.
# Must match config/execution.yaml slippage_tiers.
SLIPPAGE_TIERS: dict[str, Decimal] = {
    "BTCUSDT": Decimal("5"),
    "ETHUSDT": Decimal("10"),
    "SOLUSDT": Decimal("25"),
    "default": Decimal("15"),
}


class PaperOrder(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"]
    requested_notional_usdt: Decimal
    status: Literal["FILLED"]
    created_at: datetime


class PaperFill(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    price: Decimal
    qty: Decimal
    fee_usdt: Decimal
    slippage_bps: Decimal
    filled_at: datetime


class PaperExecutionResult(BaseModel):
    approved: bool
    order: PaperOrder | None
    fill: PaperFill | None
    reject_reasons: list[str]


class PaperExecutor:
    def __init__(
        self,
        fee_bps: Decimal = Decimal("10"),
        slippage_tiers: dict[str, Decimal] | None = None,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_tiers = slippage_tiers if slippage_tiers is not None else SLIPPAGE_TIERS

    def _slippage_bps(self, symbol: str) -> Decimal:
        """Return the slippage tier in bps for the given symbol."""
        return self.slippage_tiers.get(symbol, self.slippage_tiers["default"])

    def _apply_slippage(
        self, price: Decimal, side: Literal["BUY", "SELL"], symbol: str
    ) -> Decimal:
        """Apply slippage: BUY pays more, SELL receives less."""
        slippage_bps = self._slippage_bps(symbol)
        if side == "BUY":
            return price * (Decimal("1") + slippage_bps / Decimal("10000"))
        else:
            return price * (Decimal("1") - slippage_bps / Decimal("10000"))

    @overload
    def execute_market_buy(
        self,
        candidate: TradeCandidate,
        position_size: PositionSizeResult,
        market_price: BidAskQuote,
        executed_at: datetime,
    ) -> PaperExecutionResult: ...

    @overload
    def execute_market_buy(
        self,
        candidate: TradeCandidate,
        position_size: PositionSizeResult,
        market_price: Decimal,
        executed_at: datetime,
    ) -> PaperExecutionResult: ...

    def execute_market_buy(
        self,
        candidate: TradeCandidate,
        position_size: PositionSizeResult,
        market_price: BidAskQuote | Decimal,
        executed_at: datetime,
    ) -> PaperExecutionResult:
        """Execute a paper market buy.

        Args:
            candidate: Trade candidate with symbol and side.
            position_size: Approved position size result.
            market_price: Either a BidAskQuote (preferred) or a plain Decimal.
                When BidAskQuote is passed, BUY uses the ask price; SELL uses bid.
                When a plain Decimal is passed, a DeprecationWarning is issued
                and the price is used directly (backward-compatible behavior).
            executed_at: Timestamp for the fill record.
        """
        # ── Resolve price from BidAskQuote or plain Decimal ──────────────────────
        if isinstance(market_price, BidAskQuote):
            if candidate.side == "BUY":
                price = market_price.ask
            else:
                price = market_price.bid
            # Validate quote sanity
            if price <= Decimal("0"):
                return PaperExecutionResult(
                    approved=False,
                    order=None,
                    fill=None,
                    reject_reasons=["invalid_market_price"],
                )
        else:
            warnings.warn(
                "Passing a plain Decimal as market_price to execute_market_buy is "
                "deprecated. Pass a BidAskQuote instead (use bid for SELL, ask for BUY).",
                DeprecationWarning,
                stacklevel=2,
            )
            price = market_price
            if price <= Decimal("0"):
                return PaperExecutionResult(
                    approved=False,
                    order=None,
                    fill=None,
                    reject_reasons=["invalid_market_price"],
                )

        if not position_size.approved:
            return PaperExecutionResult(
                approved=False,
                order=None,
                fill=None,
                reject_reasons=["position_size_rejected", *position_size.reject_reasons],
            )

        fill_price = self._apply_slippage(price, "BUY", candidate.symbol)
        fee_usdt = position_size.notional_usdt * self.fee_bps / Decimal("10000")
        qty = (position_size.notional_usdt - fee_usdt) / fill_price
        slippage_bps = self._slippage_bps(candidate.symbol)

        return PaperExecutionResult(
            approved=True,
            order=PaperOrder(
                symbol=candidate.symbol,
                side="BUY",
                order_type="MARKET",
                requested_notional_usdt=position_size.notional_usdt,
                status="FILLED",
                created_at=executed_at,
            ),
            fill=PaperFill(
                symbol=candidate.symbol,
                side="BUY",
                price=fill_price,
                qty=qty,
                fee_usdt=fee_usdt,
                slippage_bps=slippage_bps,
                filled_at=executed_at,
            ),
            reject_reasons=[],
        )

    @overload
    def execute_market_sell(
        self,
        symbol: str,
        qty: Decimal,
        market_price: BidAskQuote,
        executed_at: datetime,
    ) -> PaperExecutionResult: ...

    @overload
    def execute_market_sell(
        self,
        symbol: str,
        qty: Decimal,
        market_price: Decimal,
        executed_at: datetime,
    ) -> PaperExecutionResult: ...

    def execute_market_sell(
        self,
        symbol: str,
        qty: Decimal,
        market_price: BidAskQuote | Decimal,
        executed_at: datetime,
    ) -> PaperExecutionResult:
        """Execute a paper market sell (full or partial position).

        Args:
            symbol: Trading symbol.
            qty: Quantity to sell.
            market_price: Either a BidAskQuote (preferred) or a plain Decimal.
                When BidAskQuote is passed, the bid price is used.
                When a plain Decimal is passed, a DeprecationWarning is issued.
            executed_at: Timestamp for the fill record.
        """
        if qty <= Decimal("0"):
            return PaperExecutionResult(
                approved=False,
                order=None,
                fill=None,
                reject_reasons=["invalid_qty"],
            )

        # ── Resolve price from BidAskQuote or plain Decimal ──────────────────────
        if isinstance(market_price, BidAskQuote):
            price = market_price.bid
            if price <= Decimal("0"):
                return PaperExecutionResult(
                    approved=False,
                    order=None,
                    fill=None,
                    reject_reasons=["invalid_market_price"],
                )
        else:
            warnings.warn(
                "Passing a plain Decimal as market_price to execute_market_sell is "
                "deprecated. Pass a BidAskQuote instead (bid price is used for SELL).",
                DeprecationWarning,
                stacklevel=2,
            )
            price = market_price
            if price <= Decimal("0"):
                return PaperExecutionResult(
                    approved=False,
                    order=None,
                    fill=None,
                    reject_reasons=["invalid_market_price"],
                )

        fill_price = self._apply_slippage(price, "SELL", symbol)
        notional_usdt = qty * fill_price
        fee_usdt = notional_usdt * self.fee_bps / Decimal("10000")
        slippage_bps = self._slippage_bps(symbol)

        return PaperExecutionResult(
            approved=True,
            order=PaperOrder(
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                requested_notional_usdt=notional_usdt,
                status="FILLED",
                created_at=executed_at,
            ),
            fill=PaperFill(
                symbol=symbol,
                side="SELL",
                price=fill_price,
                qty=qty,
                fee_usdt=fee_usdt,
                slippage_bps=slippage_bps,
                filled_at=executed_at,
            ),
            reject_reasons=[],
        )
