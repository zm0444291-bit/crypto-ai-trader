from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from trading.execution.paper_executor import PaperFill
from trading.portfolio.accounting import PortfolioAccount
from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.models import Fill
from trading.storage.repositories import ExecutionRecordsRepository

router = APIRouter(tags=["portfolio"])


class PositionSummary(BaseModel):
    symbol: str
    qty: Decimal
    avg_entry_price: Decimal
    market_price: Decimal
    market_value_usdt: Decimal
    unrealized_pnl_usdt: Decimal
    fees_paid_usdt: Decimal


class PortfolioStatusResponse(BaseModel):
    cash_balance_usdt: Decimal
    total_equity_usdt: Decimal
    unrealized_pnl_usdt: Decimal
    positions: list[PositionSummary]


def _plain_decimal(value: Decimal | int | float | str) -> Decimal:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    normalized = decimal_value.normalize()
    if normalized == normalized.to_integral():
        return normalized.quantize(Decimal("1"))
    return normalized


def _parse_market_prices(request: Request) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for key, value in request.query_params.multi_items():
        if key == "initial_cash_usdt":
            continue
        try:
            price = Decimal(value)
        except InvalidOperation as exc:
            raise HTTPException(
                status_code=400, detail=f"market price for {key} must be a decimal"
            ) from exc
        if price <= Decimal("0"):
            raise HTTPException(
                status_code=400, detail=f"market price for {key} must be greater than zero"
            )
        prices[key.upper()] = price
    return prices


def _to_paper_fill(fill: Fill) -> PaperFill:
    if fill.side != "BUY":
        raise HTTPException(status_code=400, detail="portfolio rebuild only supports BUY fills")
    return PaperFill(
        symbol=fill.symbol,
        side=cast(Literal["BUY", "SELL"], fill.side),
        price=fill.price,
        qty=fill.qty,
        fee_usdt=fill.fee_usdt,
        slippage_bps=fill.slippage_bps,
        filled_at=fill.filled_at.replace(tzinfo=UTC)
        if fill.filled_at.tzinfo is None
        else fill.filled_at,
    )


@router.get("/portfolio/status", response_model=PortfolioStatusResponse)
def read_portfolio_status(
    request: Request, initial_cash_usdt: Decimal = Decimal("500")
) -> PortfolioStatusResponse:
    if initial_cash_usdt < Decimal("0"):
        raise HTTPException(
            status_code=400, detail="initial_cash_usdt must be greater than or equal to zero"
        )

    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)
    account = PortfolioAccount(cash_balance=initial_cash_usdt)

    with session_factory() as session:
        fills = ExecutionRecordsRepository(session).list_fills_chronological()

    for fill in fills:
        account.apply_buy_fill(_to_paper_fill(fill))

    market_prices = _parse_market_prices(request)
    positions = [
        PositionSummary(
            symbol=position.symbol,
            qty=_plain_decimal(position.qty),
            avg_entry_price=_plain_decimal(position.avg_entry_price),
            market_price=_plain_decimal(
                market_prices.get(position.symbol, position.avg_entry_price)
            ),
            market_value_usdt=_plain_decimal(
                position.qty * market_prices.get(position.symbol, position.avg_entry_price)
            ),
            unrealized_pnl_usdt=_plain_decimal(
                position.qty
                * (
                    market_prices.get(position.symbol, position.avg_entry_price)
                    - position.avg_entry_price
                )
            ),
            fees_paid_usdt=_plain_decimal(position.fees_paid_usdt),
        )
        for position in account.positions.values()
    ]

    return PortfolioStatusResponse(
        cash_balance_usdt=_plain_decimal(account.cash_balance),
        total_equity_usdt=_plain_decimal(account.total_equity(market_prices)),
        unrealized_pnl_usdt=_plain_decimal(account.unrealized_pnl(market_prices)),
        positions=positions,
    )
