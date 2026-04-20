from datetime import UTC, datetime
from decimal import Decimal

from trading.execution.paper_executor import PaperExecutor
from trading.risk.position_sizing import PositionSizeResult
from trading.strategies.base import TradeCandidate


def make_candidate() -> TradeCandidate:
    return TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("100"),
        stop_reference=Decimal("96"),
        rule_confidence=Decimal("0.70"),
        reason="Momentum aligned.",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def approved_size(notional: Decimal = Decimal("100")) -> PositionSizeResult:
    return PositionSizeResult(
        approved=True,
        notional_usdt=notional,
        max_loss_usdt=Decimal("4"),
        reject_reasons=[],
    )


def test_paper_executor_fills_buy_with_fee_and_slippage():
    executor = PaperExecutor(fee_bps=Decimal("10"), slippage_bps=Decimal("20"))

    result = executor.execute_market_buy(
        candidate=make_candidate(),
        position_size=approved_size(Decimal("100")),
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is True
    assert result.order.symbol == "BTCUSDT"
    assert result.order.side == "BUY"
    assert result.order.status == "FILLED"
    assert result.fill.price == Decimal("100.2")
    assert result.fill.qty == Decimal("0.9970059880239520958083832335")
    assert result.fill.fee_usdt == Decimal("0.100")
    assert result.fill.slippage_bps == Decimal("20")


def test_paper_executor_rejects_unapproved_position_size():
    executor = PaperExecutor()
    rejected_size = PositionSizeResult(
        approved=False,
        notional_usdt=Decimal("0"),
        max_loss_usdt=Decimal("0"),
        reject_reasons=["below_min_notional"],
    )

    result = executor.execute_market_buy(
        candidate=make_candidate(),
        position_size=rejected_size,
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is False
    assert result.reject_reasons == ["position_size_rejected", "below_min_notional"]
    assert result.order is None
    assert result.fill is None


def test_paper_executor_rejects_non_positive_market_price():
    executor = PaperExecutor()

    result = executor.execute_market_buy(
        candidate=make_candidate(),
        position_size=approved_size(),
        market_price=Decimal("0"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is False
    assert result.reject_reasons == ["invalid_market_price"]


# ── SELL tests ─────────────────────────────────────────────────────────────────


def test_paper_executor_fills_sell_with_fee_and_slippage():
    executor = PaperExecutor(fee_bps=Decimal("10"), slippage_bps=Decimal("20"))

    result = executor.execute_market_sell(
        symbol="BTCUSDT",
        qty=Decimal("1"),
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is True
    assert result.order.symbol == "BTCUSDT"
    assert result.order.side == "SELL"
    assert result.order.status == "FILLED"
    # SELL: slippage reduces price: 100 * (1 - 20/10000) = 99.8
    assert result.fill.price == Decimal("99.8")
    assert result.fill.qty == Decimal("1")
    # fee on SELL proceeds: 99.8 * 10 / 10000 = 0.0998
    assert result.fill.fee_usdt == Decimal("0.0998")
    assert result.fill.slippage_bps == Decimal("20")


def test_paper_executor_sell_zero_qty_rejected():
    executor = PaperExecutor()

    result = executor.execute_market_sell(
        symbol="BTCUSDT",
        qty=Decimal("0"),
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is False
    assert result.reject_reasons == ["invalid_qty"]


def test_paper_executor_sell_negative_qty_rejected():
    executor = PaperExecutor()

    result = executor.execute_market_sell(
        symbol="BTCUSDT",
        qty=Decimal("-1"),
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is False
    assert result.reject_reasons == ["invalid_qty"]


def test_paper_executor_sell_zero_price_rejected():
    executor = PaperExecutor()

    result = executor.execute_market_sell(
        symbol="BTCUSDT",
        qty=Decimal("1"),
        market_price=Decimal("0"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is False
    assert result.reject_reasons == ["invalid_market_price"]


def test_paper_executor_sell_partial_qty():
    executor = PaperExecutor(fee_bps=Decimal("10"), slippage_bps=Decimal("0"))

    result = executor.execute_market_sell(
        symbol="BTCUSDT",
        qty=Decimal("0.5"),
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )

    assert result.approved is True
    assert result.fill.qty == Decimal("0.5")
    assert result.order.requested_notional_usdt == Decimal("50")
