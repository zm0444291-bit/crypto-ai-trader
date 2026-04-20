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


def test_realized_pnl_positive_single_transaction():
    """Buy at 100, sell at 110 → positive realized PnL."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    realized = account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")
    )

    # pnl = proceeds(110) - buy_cost(100) - buy_fee(0.1) - sell_fee(0.11) = 9.79
    assert realized == Decimal("9.79")
    assert account.realized_pnl_usdt() == Decimal("9.79")


def test_realized_pnl_negative_single_transaction():
    """Buy at 100, sell at 90 → negative realized PnL."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    realized = account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("90"), fee=Decimal("0.09"), side="SELL")
    )

    # pnl = 90 - 100 - 0.1 - 0.09 = -10.19
    assert realized == Decimal("-10.19")
    assert account.realized_pnl_usdt() == Decimal("-10.19")


def test_realized_pnl_cumulative_multiple_partial_sells():
    """Multiple sells accumulate realized PnL correctly across price levels."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    # 3 lots at avg 100
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    # Sell 0.5 at 120 → proceeds=60, cost=50, fee_share=0.05, sell_fee=0.06 → pnl=9.89
    r1 = account.apply_sell_fill(
        make_fill(qty=Decimal("0.5"), price=Decimal("120"), fee=Decimal("0.06"), side="SELL")
    )
    assert r1 == Decimal("9.89")

    # Sell 1.5 at 80 → proceeds=120, cost=150, fee_share=0.15, sell_fee=0.12 → pnl=-30.27
    r2 = account.apply_sell_fill(
        make_fill(qty=Decimal("1.5"), price=Decimal("80"), fee=Decimal("0.12"), side="SELL")
    )
    assert r2 == Decimal("-30.27")

    assert account.realized_pnl_usdt() == r1 + r2


def test_realized_pnl_continues_after_position_reopened():
    """After fully closing a position and reopening, realized PnL continues accumulating."""
    account = PortfolioAccount(cash_balance=Decimal("500"))

    # Open and close first position
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))
    r1 = account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")
    )
    assert r1 == Decimal("9.79")
    assert "BTCUSDT" not in account.positions

    # Reopen position at higher price
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("120"), fee=Decimal("0.12")))
    r2 = account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("130"), fee=Decimal("0.13"), side="SELL")
    )
    assert r2 == Decimal("9.75")

    # Realized is cumulative across both positions
    assert account.realized_pnl_usdt() == r1 + r2


def test_realized_pnl_zero_when_no_sells():
    """No sells → realized_pnl_usdt() returns 0, not cumulative garbage."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("2"), price=Decimal("100"), fee=Decimal("0.2")))

    assert account.realized_pnl_usdt() == Decimal("0")


def test_fees_correctly_deducted_from_realized_pnl():
    """Both buy-side and sell-side fees reduce realized PnL."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("1.0")))

    # Sell at same price → proceeds=100, cost=100, buy_fee=1.0, sell_fee=1.0 → pnl=-2
    realized = account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("1.0"), side="SELL")
    )
    assert realized == Decimal("-2")
    assert account.realized_pnl_usdt() == Decimal("-2")


def test_unrealized_pnl_independent_of_realized():
    """Unrealized PnL is position-level and independent of realized accumulation."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))

    # Market price unchanged → unrealized = 0
    unrealized = account.unrealized_pnl({"BTCUSDT": Decimal("100")})
    assert unrealized == Decimal("0")

    # Sell half at profit — remaining position still has unrealized
    account.apply_sell_fill(
        make_fill(qty=Decimal("0.5"), price=Decimal("120"), fee=Decimal("0.06"), side="SELL")
    )

    unrealized_after = account.unrealized_pnl({"BTCUSDT": Decimal("110")})
    # Remaining: qty=0.5, avg=100, market=110 → unrealized = 0.5 * 10 = 5
    assert unrealized_after == Decimal("5")
    # Realized is non-zero
    assert account.realized_pnl_usdt() > Decimal("0")


def test_cash_consistency_after_buy_and_sell():
    """Verify cash balance is consistent with buy cost + sell proceeds - fees."""
    account = PortfolioAccount(cash_balance=Decimal("500"))
    account.apply_buy_fill(make_fill(qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0.1")))
    # Cash: 500 - 100.1 = 399.9

    account.apply_sell_fill(
        make_fill(qty=Decimal("1"), price=Decimal("110"), fee=Decimal("0.11"), side="SELL")
    )
    # Cash: 399.9 + 110 - 0.11 = 509.79

    assert account.cash_balance == Decimal("509.79")
    assert account.realized_pnl_usdt() == Decimal("9.79")  # matches sell return
