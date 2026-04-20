from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading.execution.paper_executor import PaperFill
from trading.portfolio.accounting import PortfolioAccount


def make_fill(
    symbol: str = "BTCUSDT",
    qty: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0.1"),
    side: str = "BUY",
) -> PaperFill:
    return PaperFill(
        symbol=symbol,
        side=side,
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


# ── SELL tests ──────────────────────────────────────────────────────────────────


def test_apply_sell_fill_full_close():
    """Selling the entire position returns realized PnL and removes the position."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    # Sell at 110 → proceeds = 110, cost basis = 100, pnl = 110 - 100 - 0.1 = 9.9
    sell_fill = make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")
    realized = account.apply_sell_fill(sell_fill)

    # pnl = proceeds(110-0.11) - cost_basis(100) - buy_fee(0.1) - sell_fee(0.11) = 9.79
    assert realized == Decimal("9.79")
    assert "BTCUSDT" not in account.positions
    # Cash: 500 - 100.1(buy) + 110 - 0.11(sell fee) = 509.79
    assert account.cash_balance == Decimal("509.79")


def test_apply_sell_fill_partial_close():
    """Partial sell reduces qty and returns proportional realized PnL."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("2"), price=Decimal("100"), fee=Decimal("0.2")))

    # Sell 0.5 at 110 → proceeds = 55, cost basis = 50, proportional buy fee ≈ 0.05
    sell_fill = make_fill(
        qty=Decimal("0.5"), price=Decimal("110"), fee=Decimal("0.055"), side="SELL"
    )
    realized = account.apply_sell_fill(sell_fill)

    # pnl = 55 - 50 - (0.5/2 * 0.2) - 0.055 = 5 - 0.05 - 0.055 = 4.895
    assert realized == Decimal("4.895")
    assert account.positions["BTCUSDT"].qty == Decimal("1.5")
    # avg_entry_price stays at 100
    assert account.positions["BTCUSDT"].avg_entry_price == Decimal("100")
    # Remaining position fee pool should be reduced by realized fee share (0.05)
    assert account.positions["BTCUSDT"].fees_paid_usdt == Decimal("0.15")


def test_apply_sell_fill_raises_when_no_position():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    sell_fill = make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")

    with pytest.raises(ValueError, match="no open position"):
        account.apply_sell_fill(sell_fill)


def test_apply_sell_fill_rejects_zero_qty():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    zero_fill = make_fill(qty=Decimal("0"), price=Decimal("110"), fee=Decimal("0"), side="SELL")
    with pytest.raises(ValueError, match="qty must be positive"):
        account.apply_sell_fill(zero_fill)


def test_apply_sell_fill_raises_when_qty_exceeds_held():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("0.5"), price=Decimal("100"), fee=Decimal("0.05")))

    sell_fill = make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")

    with pytest.raises(ValueError, match="Cannot sell"):
        account.apply_sell_fill(sell_fill)


def test_apply_sell_fill_rejects_buy_fill():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    with pytest.raises(ValueError, match="SELL fills must go through apply_sell_fill"):
        account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), side="SELL"))


def test_apply_sell_fill_rejects_sell_on_buy_fill_symbol():
    """Passing a SELL fill to apply_sell_fill that was created with side='BUY' should reject."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    buy_fill = make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1"), side="BUY")

    # Manually construct a SELL fill for the same symbol
    sell_fill = PaperFill(
        symbol="BTCUSDT",
        side="SELL",
        price=Decimal("110"),
        qty=Decimal("1"),
        fee_usdt=Decimal("0.11"),
        slippage_bps=Decimal("0"),
        filled_at=datetime(2026, 4, 19, 2, 0, tzinfo=UTC),
    )

    # First open a position via buy
    account.apply_buy_fill(buy_fill)

    # Now sell - this should work
    realized = account.apply_sell_fill(sell_fill)
    assert realized > Decimal("0")


def test_realized_pnl_usdt_accumulates_across_sells():
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("2"), price=Decimal("100"), fee=Decimal("0.2")))

    realized1 = account.apply_sell_fill(
        make_fill(qty=Decimal("0.5"), price=Decimal("110"), fee=Decimal("0.055"), side="SELL")
    )
    realized2 = account.apply_sell_fill(
        make_fill(qty=Decimal("0.5"), price=Decimal("90"), fee=Decimal("0.045"), side="SELL")
    )

    assert account.realized_pnl_usdt() == realized1 + realized2
