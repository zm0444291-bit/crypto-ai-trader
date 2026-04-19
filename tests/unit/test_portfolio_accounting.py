from datetime import UTC, datetime
from decimal import Decimal

from trading.execution.paper_executor import PaperFill
from trading.portfolio.accounting import PortfolioAccount


def make_fill(
    symbol: str = "BTCUSDT",
    qty: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0.1"),
) -> PaperFill:
    return PaperFill(
        symbol=symbol,
        side="BUY",
        price=price,
        qty=qty,
        fee_usdt=fee,
        slippage_bps=Decimal("10"),
        filled_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def test_apply_buy_fill_reduces_cash_and_creates_position():
    account = PortfolioAccount(cash_balance=Decimal("500"))

    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    position = account.positions["BTCUSDT"]
    assert account.cash_balance == Decimal("399.9")
    assert position.qty == Decimal("1")
    assert position.avg_entry_price == Decimal("100")
    assert position.fees_paid_usdt == Decimal("0.1")


def test_apply_second_buy_fill_updates_weighted_average_price():
    account = PortfolioAccount(cash_balance=Decimal("500"))

    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("120"), fee=Decimal("0.12")))

    position = account.positions["BTCUSDT"]
    assert account.cash_balance == Decimal("279.78")
    assert position.qty == Decimal("2")
    assert position.avg_entry_price == Decimal("110")
    assert position.fees_paid_usdt == Decimal("0.22")


def test_total_equity_marks_positions_to_market():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    equity = account.total_equity({"BTCUSDT": Decimal("110")})

    assert equity == Decimal("509.9")


def test_unrealized_pnl_uses_average_entry_price():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("2"), price=Decimal("100"), fee=Decimal("0.1")))

    pnl = account.unrealized_pnl({"BTCUSDT": Decimal("110")})

    assert pnl == Decimal("20")
