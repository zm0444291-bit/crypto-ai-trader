from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from trading.execution.paper_executor import PaperFill


class Position(BaseModel):
    symbol: str
    qty: Decimal = Field(ge=0)
    avg_entry_price: Decimal = Field(ge=0)
    fees_paid_usdt: Decimal = Field(default=Decimal("0"), ge=0)
    opened_at: datetime | None = None
    stop_reference: Decimal | None = None


class PortfolioAccount(BaseModel):
    cash_balance: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)
    realized_pnl_total_usdt: Decimal = Field(default=Decimal("0"))

    def apply_buy_fill(self, fill: PaperFill) -> None:
        if fill.side == "SELL":
            raise ValueError(
                f"SELL fills must go through apply_sell_fill. Symbol={fill.symbol}, qty={fill.qty}"
            )

        gross_cost = fill.qty * fill.price
        total_cost = gross_cost + fill.fee_usdt
        self.cash_balance -= total_cost

        existing = self.positions.get(fill.symbol)
        if existing is None:
            self.positions[fill.symbol] = Position(
                symbol=fill.symbol,
                qty=fill.qty,
                avg_entry_price=fill.price,
                fees_paid_usdt=fill.fee_usdt,
                opened_at=fill.filled_at,
            )
            return

        old_cost_basis = existing.qty * existing.avg_entry_price
        new_qty = existing.qty + fill.qty
        new_cost_basis = old_cost_basis + gross_cost
        existing.qty = new_qty
        existing.avg_entry_price = new_cost_basis / new_qty
        existing.fees_paid_usdt += fill.fee_usdt

    def apply_sell_fill(self, fill: PaperFill) -> Decimal:
        """Apply a SELL fill (partial or full close).

        Returns the realized PnL in USDT for this fill.
        Raises ValueError if the position does not exist or qty exceeds held qty.
        """
        if fill.side == "BUY":
            raise ValueError(
                f"apply_sell_fill received a BUY fill. Symbol={fill.symbol}, qty={fill.qty}"
            )

        position = self.positions.get(fill.symbol)
        if position is None:
            raise ValueError(
                f"Cannot SELL {fill.symbol}: no open position found."
            )

        if fill.qty <= Decimal("0"):
            raise ValueError(
                f"Cannot sell {fill.qty} {fill.symbol}: qty must be positive."
            )

        if fill.qty > position.qty:
            raise ValueError(
                f"Cannot sell {fill.qty} {fill.symbol}: only {position.qty} held."
            )

        # Realized PnL = proceeds - cost basis of sold qty - proportional fees
        proceeds = fill.qty * fill.price
        cost_basis = fill.qty * position.avg_entry_price
        # Proportional share of the position's fees
        fee_share = (
            (fill.qty / position.qty) * position.fees_paid_usdt
            if position.fees_paid_usdt > 0
            else Decimal("0")
        )
        realized_pnl = proceeds - cost_basis - fee_share - fill.fee_usdt

        # Update cash: proceeds minus sell-side fee
        self.cash_balance += proceeds - fill.fee_usdt

        # Reduce or close position
        new_qty = position.qty - fill.qty
        if new_qty <= Decimal("0"):
            # Fully closed — also clear accumulated fees
            del self.positions[fill.symbol]
        else:
            position.qty = new_qty
            # Keep avg_entry_price unchanged for the remaining qty
            # Move the realized fee share out of the remaining position.
            position.fees_paid_usdt -= fee_share

        self.realized_pnl_total_usdt += realized_pnl

        return realized_pnl

    def realized_pnl_usdt(self) -> Decimal:
        """Return accumulated realized PnL from SELL fills."""
        return self.realized_pnl_total_usdt

    def total_equity(self, market_prices: dict[str, Decimal]) -> Decimal:
        position_value = sum(
            position.qty * market_prices.get(symbol, position.avg_entry_price)
            for symbol, position in self.positions.items()
        )
        return self.cash_balance + position_value

    def unrealized_pnl(self, market_prices: dict[str, Decimal]) -> Decimal:
        return sum(
            position.qty
            * (market_prices.get(symbol, position.avg_entry_price) - position.avg_entry_price)
            for symbol, position in self.positions.items()
        )
