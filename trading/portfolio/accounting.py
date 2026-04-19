from decimal import Decimal

from pydantic import BaseModel, Field

from trading.execution.paper_executor import PaperFill


class Position(BaseModel):
    symbol: str
    qty: Decimal = Field(ge=0)
    avg_entry_price: Decimal = Field(ge=0)
    fees_paid_usdt: Decimal = Field(default=Decimal("0"), ge=0)


class PortfolioAccount(BaseModel):
    cash_balance: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)

    def apply_buy_fill(self, fill: PaperFill) -> None:
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
            )
            return

        old_cost_basis = existing.qty * existing.avg_entry_price
        new_qty = existing.qty + fill.qty
        new_cost_basis = old_cost_basis + gross_cost
        existing.qty = new_qty
        existing.avg_entry_price = new_cost_basis / new_qty
        existing.fees_paid_usdt += fill.fee_usdt

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
