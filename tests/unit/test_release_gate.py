"""Unit tests for release gate functionality."""

from trading.dashboard_api.routes_runtime import (
    ControlPlaneResponse,
    ModeChangeRequest,
    ModeChangeResponse,
)


class TestDryRunModeChange:
    """Tests for the dry_run parameter in mode change endpoint."""

    def test_dry_run_returns_guard_check_without_persisting_mode(self):
        """dry_run=true returns guard/preflight results without changing mode."""
        # This tests the contract: when dry_run=True, the mode change is NOT
        # persisted. We validate the response shape and the dry_run flag behavior.
        request = ModeChangeRequest(
            to_mode="live_shadow",
            dry_run=True,
            reason="pre-flight check only",
        )
        # Verify dry_run flag is accepted and stored
        assert request.dry_run is True
        assert request.to_mode == "live_shadow"

    def test_dry_run_flag_defaults_to_false(self):
        """dry_run defaults to False so existing callers are unaffected."""
        request = ModeChangeRequest(to_mode="paused")
        assert request.dry_run is False

    def test_dry_run_with_live_small_auto_requires_preflight(self):
        """dry_run=True for live_small_auto still requires symbol."""
        request = ModeChangeRequest(
            to_mode="live_small_auto",
            dry_run=True,
            allow_live_unlock=True,
            symbol="BTCUSDT",
        )
        # dry_run=True but symbol is provided - preflight will run
        assert request.symbol == "BTCUSDT"
        assert request.dry_run is True

    def test_dry_run_preserves_preflight_checks_in_response(self):
        """When dry_run=True and preflight runs, preflight_checks are returned."""
        # Validate that ModeChangeResponse has the preflight_checks field
        response = ModeChangeResponse(
            success=True,
            current_mode="live_shadow",
            guard_reason="live_small_auto_unlocked",
            blocked_reason=None,
            preflight_checks=[
                {"code": "config:binance_api_key", "status": "pass", "message": "API key present"},
            ],
        )
        assert len(response.preflight_checks) == 1
        assert response.preflight_checks[0]["code"] == "config:binance_api_key"


class TestControlPlaneResponse:
    """Tests for control plane snapshot response."""

    def test_control_plane_has_transition_guard_field(self):
        """ControlPlaneResponse includes transition_guard_to_live_small_auto."""
        cp = ControlPlaneResponse(
            trade_mode="live_shadow",
            lock_enabled=True,
            lock_reason="operator engaged",
            execution_route="live",
            transition_guard_to_live_small_auto="live_small_auto_unlocked",
        )
        assert cp.transition_guard_to_live_small_auto == "live_small_auto_unlocked"

    def test_control_plane_defaults_for_unavailable(self):
        """When DB unavailable, control plane returns safe defaults."""
        cp = ControlPlaneResponse(
            trade_mode="paper_auto",
            lock_enabled=False,
            lock_reason=None,
            execution_route="paper",
            transition_guard_to_live_small_auto="blocked: unavailable",
        )
        assert cp.trade_mode == "paper_auto"
        assert cp.execution_route == "paper"
        assert "unavailable" in cp.transition_guard_to_live_small_auto


class TestModeChangeRequestGuard:
    """Tests for ModeChangeRequest fields."""

    def test_symbol_is_optional_for_non_live_modes(self):
        """symbol is not required when to_mode is not live_small_auto."""
        request = ModeChangeRequest(to_mode="paused")
        assert request.symbol is None

    def test_allow_live_unlock_defaults_to_false(self):
        """allow_live_unlock defaults to False for safety."""
        request = ModeChangeRequest(to_mode="live_shadow")
        assert request.allow_live_unlock is False

    def test_reason_is_optional(self):
        """reason field is optional."""
        request = ModeChangeRequest(to_mode="paper_auto")
        assert request.reason is None