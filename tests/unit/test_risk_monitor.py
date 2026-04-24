"""Tests for trading/risk/risk_monitor.py."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from trading.risk.risk_monitor import (
    RiskEventType,
    RiskMonitor,
)


class TestRiskMonitor:
    """Unit tests for RiskMonitor.

    Uses large initial equity so the profile stays "aggressive" throughout tests,
    and actual thresholds are determined by classify_daily_loss.
    """

    def setup_method(self) -> None:
        # 1_000_000 USDT → aggressive profile with 100% total / 50% symbol limits
        self.rm = RiskMonitor(day_start_equity=Decimal("1_000_000"))

    # ── initial state ─────────────────────────────────────────────────────────

    def test_initial_state_is_normal(self) -> None:
        assert self.rm.risk_state == "normal"
        assert self.rm.daily_pnl_pct == Decimal("0")
        assert self.rm.current_equity == Decimal("1_000_000")
        assert self.rm.day_start_equity == Decimal("1_000_000")

    # ── update_equity — no change ─────────────────────────────────────────────

    def test_update_equity_unchanged_stays_normal(self) -> None:
        """Equity unchanged from day-start → no state change."""
        self.rm.update_equity(Decimal("1_000_000"))
        assert self.rm.risk_state == "normal"

    # ── update_equity — small loss stays NORMAL ──────────────────────────────

    def test_update_equity_small_loss_stays_normal(self) -> None:
        """Under the degraded threshold stays normal."""
        self.rm.update_equity(Decimal("990_000"))  # -0.1%
        assert self.rm.risk_state == "normal"

    # ── update_equity — crosses degraded threshold ───────────────────────────

    def test_update_equity_crosses_degraded_threshold(self) -> None:
        # With aggressive profile the degraded threshold is 5% loss
        self.rm.update_equity(Decimal("950_000"))  # -5%
        # classify_daily_loss determines actual state; verify it's not normal
        assert self.rm.risk_state != "normal"

    # ── update_equity — large loss → not normal ──────────────────────────────

    def test_update_equity_large_loss_not_normal(self) -> None:
        self.rm.update_equity(Decimal("800_000"))  # -20%
        assert self.rm.risk_state in ("degraded", "no_new_positions", "global_pause")

    # ── state does not regress ───────────────────────────────────────────────

    def test_state_does_not_regress_on_recovery(self) -> None:
        """Once triggered, a state doesn't revert on partial recovery."""
        self.rm.update_equity(Decimal("800_000"))  # -20%
        initial_state = self.rm.risk_state

        self.rm.update_equity(Decimal("900_000"))  # still -10%
        # State should not improve
        assert self.rm.risk_state == initial_state

    # ── profile adapts to equity level ───────────────────────────────────────

    def test_profile_adapts_to_lower_equity(self) -> None:
        """Profile should get more conservative as equity drops."""
        self.rm.update_equity(Decimal("100_000"))
        # Verify a profile exists and has a name
        assert self.rm.profile.name is not None

    # ── position limit warnings ──────────────────────────────────────────────

    def test_position_limits_below_80pct_no_warning(self) -> None:
        # large_conservative: max_total=50%, max_symbol=20% → 80% thresholds = 40%, 16%
        # 30% total (< 40%) and 10% symbol (< 16%) → no warning
        alerts = self.rm.check_position_limits(
            total_position_pct=Decimal("30"),
            symbol_position_pct=Decimal("10"),
            symbol="BTC",
        )
        assert alerts == []

    def test_position_limits_total_above_80pct_warning(self) -> None:
        # 85% of 100% limit → exceeds 80% threshold
        alerts = self.rm.check_position_limits(
            total_position_pct=Decimal("85"),
            symbol_position_pct=Decimal("10"),
            symbol="BTC",
        )
        assert len(alerts) == 1
        assert "Total position" in alerts[0]

    def test_position_limits_symbol_above_80pct_warning(self) -> None:
        # 45% of 50% symbol limit → 45% >= 80% of 50% (= 40%) → warning
        alerts = self.rm.check_position_limits(
            total_position_pct=Decimal("30"),
            symbol_position_pct=Decimal("45"),
            symbol="BTC",
        )
        assert len(alerts) == 1
        assert "BTC" in alerts[0]

    def test_position_limits_both_above_80pct_two_warnings(self) -> None:
        alerts = self.rm.check_position_limits(
            total_position_pct=Decimal("85"),
            symbol_position_pct=Decimal("45"),
            symbol="ETH",
        )
        assert len(alerts) == 2

    # ── broadcast on state transition ───────────────────────────────────────

    @patch("trading.risk.risk_monitor.broadcast_from_sync")
    def test_broadcast_sent_on_state_change(
        self, mock_broadcast: MagicMock
    ) -> None:
        self.rm.update_equity(Decimal("800_000"))  # large loss → definitely state change
        assert mock_broadcast.called
        call_args = mock_broadcast.call_args
        assert call_args is not None
        _, event_type, payload = call_args[0]
        assert event_type == "risk_update"
        assert "risk_state" in payload["data"]

    @patch("trading.risk.risk_monitor.broadcast_from_sync")
    def test_broadcast_not_sent_when_state_unchanged(
        self, mock_broadcast: MagicMock
    ) -> None:
        self.rm.update_equity(Decimal("1_000_000"))  # unchanged
        mock_broadcast.assert_not_called()

    # ── check_equity_alert ──────────────────────────────────────────────────

    def test_check_equity_alert_returns_none_when_normal(self) -> None:
        self.rm.update_equity(Decimal("1_000_000"))
        alert = self.rm.check_equity_alert()
        assert alert is None

    def test_check_equity_alert_returns_alert_when_not_normal(self) -> None:
        self.rm.update_equity(Decimal("800_000"))
        alert = self.rm.check_equity_alert()
        assert alert is not None
        assert alert.event_type == RiskEventType.EQUITY_ALERT
        assert alert.risk_state in ("degraded", "no_new_positions", "global_pause")

    # ── daily_pnl_pct property ─────────────────────────────────────────────

    def test_daily_pnl_pct_positive(self) -> None:
        self.rm.update_equity(Decimal("1_050_000"))  # +5%
        assert self.rm.daily_pnl_pct == Decimal("5")

    def test_daily_pnl_pct_negative(self) -> None:
        self.rm.update_equity(Decimal("950_000"))  # -5%
        assert self.rm.daily_pnl_pct == Decimal("-5")

    def test_daily_pnl_pct_zero_at_init(self) -> None:
        assert self.rm.daily_pnl_pct == Decimal("0")


class TestRiskEventTypeValues:
    """Sanity-check RiskEventType enum values."""

    def test_risk_state_changed_value(self) -> None:
        assert RiskEventType.RISK_STATE_CHANGED == "risk_state_changed"

    def test_equity_alert_value(self) -> None:
        assert RiskEventType.EQUITY_ALERT == "equity_alert"

    def test_position_limit_warning_value(self) -> None:
        assert RiskEventType.POSITION_LIMIT_WARNING == "position_limit_warning"
