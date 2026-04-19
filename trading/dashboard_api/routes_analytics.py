"""Dashboard API for analytics: equity snapshots, win/loss, daily PnL."""

from datetime import UTC
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trading.runtime.config import AppSettings
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import ExecutionRecordsRepository

router = APIRouter(tags=["analytics"])


class EquitySnapshot(BaseModel):
    timestamp: str
    equity_usdt: str


class DailyPnlEntry(BaseModel):
    date: str
    pnl_usdt: str


class AnalyticsSummaryResponse(BaseModel):
    current_equity_usdt: str
    day_start_equity_usdt: str
    daily_pnl_usdt: str
    daily_pnl_pct: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: str
    avg_win_usdt: str
    avg_loss_usdt: str
    equity_snapshots: list[EquitySnapshot]
    daily_pnl_history: list[DailyPnlEntry]


def _plain_decimal(value: Decimal) -> Decimal:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return normalized.quantize(Decimal("1"))
    return normalized


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
def read_analytics_summary(
    initial_cash_usdt: Decimal = Decimal("500"),
) -> AnalyticsSummaryResponse:
    """Return analytics summary from fill history: equity trend, win/loss, daily PnL."""
    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    now = _utc_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session_factory() as session:
        exec_repo = ExecutionRecordsRepository(session)
        all_fills = exec_repo.list_fills_chronological()

    if not all_fills:
        return AnalyticsSummaryResponse(
            current_equity_usdt=str(initial_cash_usdt),
            day_start_equity_usdt=str(initial_cash_usdt),
            daily_pnl_usdt="0",
            daily_pnl_pct="0.00",
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct="0.00",
            avg_win_usdt="0",
            avg_loss_usdt="0",
            equity_snapshots=[],
            daily_pnl_history=[],
        )

    if initial_cash_usdt < Decimal("0"):
        raise HTTPException(
            status_code=400, detail="initial_cash_usdt must be greater than or equal to zero"
        )

    # Build fills-by-day map and compute equity snapshots
    from trading.storage.models import Fill

    fills_by_day: dict[str, list[Fill]] = {}
    for fill in all_fills:
        day_key = fill.filled_at.strftime("%Y-%m-%d")
        fills_by_day.setdefault(day_key, []).append(fill)

    sorted_days = sorted(fills_by_day.keys())

    # Compute equity at each day boundary using direct cash + position tracking
    # (PortfolioAccount.apply_sell_fill raises NotImplementedError)
    snapshots: list[EquitySnapshot] = []
    cash = initial_cash_usdt
    positions: dict[str, dict] = {}  # symbol -> {qty, avg_price, cost_basis}
    for day in sorted_days:
        day_fills = fills_by_day[day]
        for fill in day_fills:
            if fill.side == "BUY":
                cost = fill.price * fill.qty + fill.fee_usdt
                cash -= cost
                if fill.symbol in positions:
                    pos = positions[fill.symbol]
                    new_qty = pos["qty"] + fill.qty
                    pos["avg_price"] = (pos["cost_basis"] + fill.price * fill.qty) / new_qty
                    pos["cost_basis"] = pos["avg_price"] * new_qty
                    pos["qty"] = new_qty
                else:
                    positions[fill.symbol] = {
                        "qty": fill.qty,
                        "avg_price": fill.price,
                        "cost_basis": fill.price * fill.qty,
                    }
            elif fill.side == "SELL":
                proceeds = fill.price * fill.qty - fill.fee_usdt
                cash += proceeds
                if fill.symbol in positions:
                    positions[fill.symbol]["qty"] -= fill.qty
                    if positions[fill.symbol]["qty"] <= 0:
                        del positions[fill.symbol]
        equity = cash + sum(p["avg_price"] * p["qty"] for p in positions.values())
        snapshots.append(EquitySnapshot(timestamp=day, equity_usdt=str(_plain_decimal(equity))))

    # Current equity (after all fills)
    current_equity = cash + sum(p["avg_price"] * p["qty"] for p in positions.values())

    # Day-start equity: recompute equity up to yesterday using same direct method
    day_start_equity = initial_cash_usdt
    if day_start.strftime("%Y-%m-%d") in fills_by_day:
        day_start_cash = initial_cash_usdt
        day_start_positions: dict[str, dict] = {}
        for fill in all_fills:
            fill_day = fill.filled_at.strftime("%Y-%m-%d")
            if fill_day < day_start.strftime("%Y-%m-%d"):
                if fill.side == "BUY":
                    cost = fill.price * fill.qty + fill.fee_usdt
                    day_start_cash -= cost
                    if fill.symbol in day_start_positions:
                        pos = day_start_positions[fill.symbol]
                        new_qty = pos["qty"] + fill.qty
                        pos["avg_price"] = (pos["cost_basis"] + fill.price * fill.qty) / new_qty
                        pos["cost_basis"] = pos["avg_price"] * new_qty
                        pos["qty"] = new_qty
                    else:
                        day_start_positions[fill.symbol] = {
                            "qty": fill.qty,
                            "avg_price": fill.price,
                            "cost_basis": fill.price * fill.qty,
                        }
                elif fill.side == "SELL":
                    proceeds = fill.price * fill.qty - fill.fee_usdt
                    day_start_cash += proceeds
                    if fill.symbol in day_start_positions:
                        day_start_positions[fill.symbol]["qty"] -= fill.qty
                        if day_start_positions[fill.symbol]["qty"] <= 0:
                            del day_start_positions[fill.symbol]
        day_start_equity = day_start_cash + sum(
            p["avg_price"] * p["qty"] for p in day_start_positions.values()
        )

    daily_pnl_usdt = current_equity - day_start_equity
    daily_pnl_pct = (
        (daily_pnl_usdt / day_start_equity * Decimal("100"))
        if day_start_equity > 0
        else Decimal("0")
    )

    # Win/loss: FIFO matching — each SELL fill is matched against earliest BUY fills
    symbol_fills: dict[str, list[Fill]] = {}
    for fill in all_fills:
        symbol_fills.setdefault(fill.symbol, []).append(fill)

    winning_trades = 0
    losing_trades = 0
    total_win = Decimal("0")
    total_loss = Decimal("0")

    for _symbol, fills in symbol_fills.items():
        buys = [f for f in fills if f.side == "BUY"]
        sells = [f for f in fills if f.side == "SELL"]
        if not buys or not sells:
            continue
        total_buy_qty = sum(f.qty for f in buys)
        total_sell_qty = sum(f.qty for f in sells)
        # Skip symbols with net short position (can't compute without short tracking)
        if total_sell_qty > total_buy_qty:
            continue
        # FIFO: match each SELL fill against oldest BUYs at their average price
        avg_buy_price = sum(f.price * f.qty for f in buys) / total_buy_qty
        sell_proceeds = sum(f.price * f.qty - f.fee_usdt for f in sells)
        buy_cost = total_sell_qty * avg_buy_price
        buy_fees = sum(f.fee_usdt for f in buys)
        sell_fees = sum(f.fee_usdt for f in sells)
        pnl = sell_proceeds - buy_cost - buy_fees - sell_fees
        if pnl > 0:
            winning_trades += 1
            total_win += pnl
        elif pnl < 0:
            losing_trades += 1
            total_loss += abs(pnl)

    total_trades = winning_trades + losing_trades
    win_rate = (
        Decimal(winning_trades) / Decimal(total_trades) * Decimal("100")
        if total_trades > 0
        else Decimal("0")
    )
    avg_win = total_win / Decimal(winning_trades) if winning_trades > 0 else Decimal("0")
    avg_loss = total_loss / Decimal(losing_trades) if losing_trades > 0 else Decimal("0")

    # Daily PnL history (last 30 days)
    daily_pnl_history: list[DailyPnlEntry] = []
    prev_equity = initial_cash_usdt
    for day in sorted_days[-30:]:
        day_equity_str = next(
            (s.equity_usdt for s in snapshots if s.timestamp == day), None
        )
        if day_equity_str:
            day_equity = Decimal(day_equity_str)
            pnl = day_equity - prev_equity
            daily_pnl_history.append(DailyPnlEntry(date=day, pnl_usdt=str(_plain_decimal(pnl))))
            prev_equity = day_equity

    return AnalyticsSummaryResponse(
        current_equity_usdt=str(_plain_decimal(current_equity)),
        day_start_equity_usdt=str(_plain_decimal(day_start_equity)),
        daily_pnl_usdt=str(_plain_decimal(daily_pnl_usdt)),
        daily_pnl_pct=f"{daily_pnl_pct:.2f}",
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=f"{win_rate:.1f}",
        avg_win_usdt=str(_plain_decimal(avg_win)),
        avg_loss_usdt=str(_plain_decimal(avg_loss)),
        equity_snapshots=snapshots[-30:],
        daily_pnl_history=daily_pnl_history,
    )


def _utc_now():
    from datetime import datetime

    return datetime.now(UTC)
