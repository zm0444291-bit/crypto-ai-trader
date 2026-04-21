from decimal import Decimal

import pytest

from trading.risk.profiles import select_risk_profile
from trading.risk.state import (
    ConsecutiveLossTracker,
    DailyLossDecision,
    RiskState,
    classify_daily_loss,
)


class TestClassifyDailyLoss:
    @pytest.fixture
    def small_profile(self):
        return select_risk_profile(Decimal("500"))

    def test_normal_state_at_zero_loss(self, small_profile):
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("1000"),
            profile=small_profile,
        )
        assert decision.risk_state == "normal"
        assert decision.daily_pnl_pct == Decimal("0")

    def test_normal_state_at_small_loss(self, small_profile):
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("980"),
            profile=small_profile,
        )
        assert decision.risk_state == "normal"
        assert decision.daily_pnl_pct == Decimal("-2")

    def test_normal_state_at_caution_boundary_minus_epsilon(self, small_profile):
        # -4.99% is still normal (above -5% caution threshold)
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("950.1"),
            profile=small_profile,
        )
        assert decision.risk_state == "normal"

    def test_degraded_state_at_caution_threshold(self, small_profile):
        # -5% loss should be degraded
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("950"),
            profile=small_profile,
        )
        assert decision.risk_state == "degraded"
        assert decision.daily_pnl_pct == Decimal("-5")

    def test_degraded_state_between_caution_and_no_new_positions(self, small_profile):
        # -6% loss should be degraded
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("940"),
            profile=small_profile,
        )
        assert decision.risk_state == "degraded"

    def test_no_new_positions_at_threshold(self, small_profile):
        # -7% loss should be no_new_positions
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("930"),
            profile=small_profile,
        )
        assert decision.risk_state == "no_new_positions"

    def test_no_new_positions_between_thresholds(self, small_profile):
        # -9% loss should be no_new_positions
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("910"),
            profile=small_profile,
        )
        assert decision.risk_state == "no_new_positions"

    def test_global_pause_at_threshold(self, small_profile):
        # -10% loss should be global_pause
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("900"),
            profile=small_profile,
        )
        assert decision.risk_state == "global_pause"

    def test_global_pause_worse_than_threshold(self, small_profile):
        # -15% loss should be global_pause
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("850"),
            profile=small_profile,
        )
        assert decision.risk_state == "global_pause"

    def test_daily_pnl_pct_is_positive_for_loss(self, small_profile):
        # daily_pnl_pct stored in decision should be positive (absolute loss value)
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("930"),
            profile=small_profile,
        )
        assert decision.daily_pnl_pct == Decimal("-7")

    def test_reason_includes_threshold(self, small_profile):
        decision = classify_daily_loss(
            day_start_equity=Decimal("1000"),
            current_equity=Decimal("930"),
            profile=small_profile,
        )
        assert "7" in decision.reason
        assert "no-new-positions" in decision.reason.lower().replace("_", "")


class TestRiskStateTransitions:
    def test_medium_profile_has_different_thresholds(self):
        profile = select_risk_profile(Decimal("2000"))
        assert profile.name == "medium_conservative"
        # medium: caution=3, no_new=5, global_pause=7
        decision = classify_daily_loss(
            day_start_equity=Decimal("2000"),
            current_equity=Decimal("1930"),
            profile=profile,
        )
        # -70/2000 = -3.5%, which is >= 3% caution but < 5% no_new_positions
        assert decision.risk_state == "degraded"

    def test_large_profile_has_different_thresholds(self):
        profile = select_risk_profile(Decimal("20000"))
        assert profile.name == "large_conservative"
        # large: caution=2, no_new=4, global_pause=5
        decision = classify_daily_loss(
            day_start_equity=Decimal("20000"),
            current_equity=Decimal("19600"),
            profile=profile,
        )
        # -400/20000 = -2%, which is >= 2% caution but < 4% no_new_positions
        assert decision.risk_state == "degraded"


class TestDailyLossDecisionModel:
    def test_has_required_fields(self):
        decision = DailyLossDecision(
            risk_state="normal",
            daily_pnl_pct=Decimal("-2.5"),
            reason="Daily loss within normal range",
        )
        assert decision.risk_state == "normal"
        assert decision.daily_pnl_pct == Decimal("-2.5")
        assert decision.reason == "Daily loss within normal range"

    def test_risk_state_is_valid_literal(self):
        valid_states: list[RiskState] = [
            "normal",
            "degraded",
            "no_new_positions",
            "global_pause",
            "emergency_stop",
        ]
        for state in valid_states:
            decision = DailyLossDecision(
                risk_state=state,
                daily_pnl_pct=Decimal("0"),
                reason="test",
            )
            assert decision.risk_state == state


class TestConsecutiveLossTracker:
    """VA-0.3.1 / VA-0.3.2 / VA-0.3.3"""

    def test_record_loss_increments(self):
        tracker = ConsecutiveLossTracker()
        tracker.record_loss("BTCUSDT")
        assert tracker.get_consecutive_losses("BTCUSDT") == 1
        tracker.record_loss("BTCUSDT")
        assert tracker.get_consecutive_losses("BTCUSDT") == 2

    def test_record_win_resets_target_only(self):
        tracker = ConsecutiveLossTracker()
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("ETHUSDT")
        assert tracker.get_consecutive_losses("BTCUSDT") == 2
        assert tracker.get_consecutive_losses("ETHUSDT") == 1

        tracker.record_win("BTCUSDT")
        assert tracker.get_consecutive_losses("BTCUSDT") == 0
        assert tracker.get_consecutive_losses("ETHUSDT") == 1  # unaffected

    def test_btc_loss_does_not_affect_eth(self):
        tracker = ConsecutiveLossTracker()
        for _ in range(3):
            tracker.record_loss("BTCUSDT")
        assert tracker.get_consecutive_losses("BTCUSDT") == 3
        assert tracker.get_consecutive_losses("ETHUSDT") == 0

    def test_get_consecutive_losses_unknown_symbol_returns_zero(self):
        tracker = ConsecutiveLossTracker()
        assert tracker.get_consecutive_losses("SOLUSDT") == 0

    def test_to_dict(self):
        tracker = ConsecutiveLossTracker()
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("ETHUSDT")
        d = tracker.to_dict()
        assert d["BTCUSDT"] == 2
        assert d["ETHUSDT"] == 1

    def test_from_dict_roundtrip(self):
        tracker = ConsecutiveLossTracker()
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("BTCUSDT")
        tracker.record_loss("ETHUSDT")

        d = tracker.to_dict()
        restored = ConsecutiveLossTracker.from_dict(d)

        assert restored.get_consecutive_losses("BTCUSDT") == 2
        assert restored.get_consecutive_losses("ETHUSDT") == 1

    def test_from_dict_empty(self):
        restored = ConsecutiveLossTracker.from_dict({})
        assert restored.get_consecutive_losses("BTCUSDT") == 0

    def test_from_dict_legacy_format_ignored(self):
        """Legacy tracker stored a plain integer; from_dict should not crash."""
        legacy = {"": 5}  # old global-int format
        restored = ConsecutiveLossTracker.from_dict(legacy)
        # Should start fresh — legacy data ignored
        assert restored.get_consecutive_losses("BTCUSDT") == 0
        assert restored.get_consecutive_losses("ETHUSDT") == 0
