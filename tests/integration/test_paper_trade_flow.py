from datetime import UTC, datetime
from decimal import Decimal

from trading.execution.paper_executor import PaperExecutor
from trading.portfolio.accounting import PortfolioAccount
from trading.risk.position_sizing import calculate_position_size
from trading.risk.pre_trade import PortfolioRiskSnapshot, evaluate_pre_trade_risk
from trading.risk.profiles import default_risk_profiles
from trading.strategies.base import TradeCandidate


def test_candidate_to_paper_fill_to_portfolio_update():
    candidate = TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("100"),
        stop_reference=Decimal("96"),
        rule_confidence=Decimal("0.70"),
        reason="Momentum aligned.",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )
    profile = default_risk_profiles()[0]
    account = PortfolioAccount(cash_balance=Decimal("500"))
    snapshot = PortfolioRiskSnapshot(
        account_equity=Decimal("500"),
        day_start_equity=Decimal("500"),
        total_position_pct=Decimal("0"),
        symbol_position_pct=Decimal("0"),
        open_positions=0,
        daily_order_count=0,
        symbol_daily_trade_count=0,
        consecutive_losses=0,
        data_is_fresh=True,
        kill_switch_enabled=False,
    )

    risk_decision = evaluate_pre_trade_risk(candidate, snapshot, profile)
    position_size = calculate_position_size(candidate, risk_decision, profile, Decimal("500"))
    execution = PaperExecutor(
        fee_bps=Decimal("10"), slippage_tiers={"default": Decimal("0")}
    ).execute_market_buy(
        candidate=candidate,
        position_size=position_size,
        market_price=Decimal("100"),
        executed_at=datetime(2026, 4, 19, 1, 1, tzinfo=UTC),
    )
    account.apply_buy_fill(execution.fill)

    assert risk_decision.approved is True
    assert position_size.approved is True
    assert execution.approved is True
    assert account.positions["BTCUSDT"].qty == Decimal("1.4985")
    assert account.cash_balance == Decimal("350")
