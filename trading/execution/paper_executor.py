from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from trading.risk.position_sizing import PositionSizeResult
from trading.strategies.base import TradeCandidate


class PaperOrder(BaseModel):
    symbol: str
    side: Literal["BUY"]
    order_type: Literal["MARKET"]
    requested_notional_usdt: Decimal
    status: Literal["FILLED"]
    created_at: datetime


class PaperFill(BaseModel):
    symbol: str
    side: Literal["BUY"]
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
        slippage_bps: Decimal = Decimal("0"),
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def execute_market_buy(
        self,
        candidate: TradeCandidate,
        position_size: PositionSizeResult,
        market_price: Decimal,
        executed_at: datetime,
    ) -> PaperExecutionResult:
        if not position_size.approved:
            return PaperExecutionResult(
                approved=False,
                order=None,
                fill=None,
                reject_reasons=["position_size_rejected", *position_size.reject_reasons],
            )

        if market_price <= Decimal("0"):
            return PaperExecutionResult(
                approved=False,
                order=None,
                fill=None,
                reject_reasons=["invalid_market_price"],
            )

        fill_price = market_price * (Decimal("1") + self.slippage_bps / Decimal("10000"))
        fee_usdt = position_size.notional_usdt * self.fee_bps / Decimal("10000")
        qty = (position_size.notional_usdt - fee_usdt) / fill_price

        return PaperExecutionResult(
            approved=True,
            order=PaperOrder(
                symbol=candidate.symbol,
                side=candidate.side,
                order_type="MARKET",
                requested_notional_usdt=position_size.notional_usdt,
                status="FILLED",
                created_at=executed_at,
            ),
            fill=PaperFill(
                symbol=candidate.symbol,
                side=candidate.side,
                price=fill_price,
                qty=qty,
                fee_usdt=fee_usdt,
                slippage_bps=self.slippage_bps,
                filled_at=executed_at,
            ),
            reject_reasons=[],
        )
