from datetime import datetime
from decimal import Decimal

import pytest

from trading.risk.pre_trade import (
    PortfolioRiskSnapshot,
    evaluate_pre_trade_risk,
)
from trading.risk.profiles import select_risk_profile
from trading.strategies.base import TradeCandidate


@pytest.fixture
def small_profile():
    return select_risk_profile(Decimal("500"))


@pytest.fixture
def base_candidate():
    return TradeCandidate(
        strategy_name="test_strategy",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("50000"),
        stop_reference=Decimal("49000"),
        rule_confidence=Decimal("0.8"),
        reason="Test candidate",
        created_at=datetime.now(),
    )


@pytest.fixture
def base_snapshot():
    return PortfolioRiskSnapshot(
        account_equity=Decimal("1000"),
        day_start_equity=Decimal("1000"),
        total_position_pct=Decimal("0"),
        symbol_position_pct=Decimal("0"),
        open_positions=0,
        daily_order_count=0,
        symbol_daily_trade_count=0,
        consecutive_losses=0,
        data_is_fresh=True,
        kill_switch_enabled=False,
    )


class TestApprovesNormalCandidate:
    def test_approves_normal_candidate_with_size_multiplier_1(
        self, small_profile, base_candidate, base_snapshot
    ):
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is True
        assert decision.risk_state == "normal"
        assert decision.size_multiplier == Decimal("1")
        assert decision.reject_reasons == []


class TestDegradedDailyLoss:
    def test_degraded_daily_loss_approves_with_size_multiplier_0_5(
        self, small_profile, base_candidate, base_snapshot
    ):
        # -5% loss = degraded for small profile (caution at 5%)
        base_snapshot.account_equity = Decimal("950")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is True
        assert decision.risk_state == "degraded"
        assert decision.size_multiplier == Decimal("0.5")
        assert decision.reject_reasons == []


class TestKillSwitch:
    def test_kill_switch_rejects_with_emergency_stop(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.kill_switch_enabled = True
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "emergency_stop"
        assert decision.size_multiplier == Decimal("0")
        assert decision.reject_reasons == ["kill_switch_enabled"]


class TestStaleData:
    def test_stale_data_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.data_is_fresh = False
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert decision.size_multiplier == Decimal("0")
        assert decision.reject_reasons == ["stale_market_data"]


class TestDailyLossNoNewPositions:
    def test_no_new_positions_daily_loss_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        # -7% loss = no_new_positions for small profile
        base_snapshot.account_equity = Decimal("930")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert decision.size_multiplier == Decimal("0")
        assert "daily_loss_no_new_positions" in decision.reject_reasons


class TestDailyLossGlobalPause:
    def test_global_pause_daily_loss_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        # -10% loss = global_pause for small profile
        base_snapshot.account_equity = Decimal("900")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "global_pause"
        assert decision.size_multiplier == Decimal("0")
        assert "daily_loss_global_pause" in decision.reject_reasons


class TestMaxTotalPosition:
    def test_max_total_position_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        # small_profile max_total_position_pct = 70
        base_snapshot.total_position_pct = Decimal("70")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert "max_total_position_reached" in decision.reject_reasons

    def test_max_total_position_just_below_approves(
        self, small_profile, base_candidate, base_snapshot
    ):
        # Just below threshold should approve
        base_snapshot.total_position_pct = Decimal("69.99")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is True
        assert decision.risk_state == "normal"


class TestMaxSymbolPosition:
    def test_max_symbol_position_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        # small_profile max_symbol_position_pct = 30
        base_snapshot.symbol_position_pct = Decimal("30")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert "max_symbol_position_reached" in decision.reject_reasons

    def test_max_symbol_position_just_below_approves(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.symbol_position_pct = Decimal("29.99")
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
        )
        assert decision.approved is True
        assert decision.risk_state == "normal"


class TestMaxDailyOrders:
    def test_max_daily_orders_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.daily_order_count = 15
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_daily_orders=15,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert "max_daily_orders_reached" in decision.reject_reasons

    def test_max_daily_orders_just_below_approves(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.daily_order_count = 14
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_daily_orders=15,
        )
        assert decision.approved is True


class TestMaxSymbolDailyTrades:
    def test_max_symbol_daily_trades_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.symbol_daily_trade_count = 4
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_symbol_daily_trades=4,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert "max_symbol_daily_trades_reached" in decision.reject_reasons

    def test_max_symbol_daily_trades_just_below_approves(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.symbol_daily_trade_count = 3
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_symbol_daily_trades=4,
        )
        assert decision.approved is True


class TestMaxConsecutiveLosses:
    def test_max_consecutive_losses_rejects(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.consecutive_losses = 4
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_consecutive_losses=4,
        )
        assert decision.approved is False
        assert decision.risk_state == "no_new_positions"
        assert "max_consecutive_losses_reached" in decision.reject_reasons

    def test_max_consecutive_losses_just_below_approves(
        self, small_profile, base_candidate, base_snapshot
    ):
        base_snapshot.consecutive_losses = 3
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_consecutive_losses=4,
        )
        assert decision.approved is True


class TestMultipleRejectReasons:
    def test_accumulates_multiple_reject_reasons(
        self, small_profile, base_candidate, base_snapshot
    ):
        # Trigger multiple reject conditions
        base_snapshot.total_position_pct = Decimal("70")
        base_snapshot.symbol_position_pct = Decimal("30")
        base_snapshot.daily_order_count = 15
        decision = evaluate_pre_trade_risk(
            candidate=base_candidate,
            snapshot=base_snapshot,
            profile=small_profile,
            max_daily_orders=15,
        )
        assert decision.approved is False
        assert "max_total_position_reached" in decision.reject_reasons
        assert "max_symbol_position_reached" in decision.reject_reasons
        assert "max_daily_orders_reached" in decision.reject_reasons
