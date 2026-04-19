"""Unit tests for the ExecutionGate and LiveTradingLock."""

from trading.execution.gate import (
    TRADE_MODES,
    ExecutionDecision,
    ExecutionGate,
    LiveTradingLock,
    compute_execution_route,
)


class TestExecutionGate:
    def _decide(
        self,
        mode: TRADE_MODES,
        lock: LiveTradingLock,
        risk_approved: bool = True,
        kill_switch_enabled: bool = False,
    ) -> ExecutionDecision:
        gate = ExecutionGate()
        return gate.decide(
            mode=mode,
            lock=lock,
            risk_approved=risk_approved,
            kill_switch_enabled=kill_switch_enabled,
        )

    # ── paused mode ──────────────────────────────────────────────────────────

    def test_paused_is_blocked(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("paused", lock)
        assert result.allowed is False
        assert result.route == "blocked"
        assert result.reason == "mode_paused"

    # ── paper_auto mode ────────────────────────────────────────────────────────

    def test_paper_auto_routes_to_paper_when_risk_approved(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("paper_auto", lock, risk_approved=True)
        assert result.allowed is True
        assert result.route == "paper"
        assert result.reason == "paper_auto_approved"

    def test_paper_auto_blocked_when_risk_rejected(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("paper_auto", lock, risk_approved=False)
        assert result.allowed is False
        assert result.route == "blocked"
        assert result.reason == "risk_rejected"

    # ── live_shadow mode ─────────────────────────────────────────────────────

    def test_live_shadow_routes_to_shadow(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("live_shadow", lock)
        assert result.allowed is True
        assert result.route == "shadow"
        assert result.reason == "live_shadow_approved"

    # ── live_small_auto mode ──────────────────────────────────────────────────

    def test_live_small_auto_blocked_by_default(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("live_small_auto", lock)
        assert result.allowed is False
        assert result.route == "blocked"
        assert result.reason == "live_small_auto_requires_explicit_unlock"

    # ── kill switch override ──────────────────────────────────────────────────

    def test_kill_switch_blocks_all_modes(self):
        lock = LiveTradingLock(enabled=False)
        for mode in ("paused", "paper_auto", "live_shadow", "live_small_auto"):
            result = self._decide(mode, lock, kill_switch_enabled=True)
            assert result.allowed is False
            assert result.route == "blocked"
            assert result.reason == "kill_switch_active"

    # ── live trading lock override ─────────────────────────────────────────────

    def test_lock_enabled_blocks_live_modes(self):
        lock = LiveTradingLock(enabled=True, reason="maintenance")
        for mode in ("live_shadow", "live_small_auto"):
            result = self._decide(mode, lock)
            assert result.allowed is False
            assert result.route == "blocked"
            assert result.reason == "maintenance"

    def test_lock_enabled_does_not_block_paper_mode(self):
        lock = LiveTradingLock(enabled=True, reason="maintenance")
        result = self._decide("paper_auto", lock, risk_approved=True)
        assert result.allowed is True
        assert result.route == "paper"
        assert result.reason == "paper_auto_approved"

    # ── route returned in decision ───────────────────────────────────────────

    def test_route_paper_included_in_decision(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("paper_auto", lock, risk_approved=True)
        assert result.route == "paper"
        assert result.mode == "paper_auto"

    def test_route_shadow_included_in_decision(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("live_shadow", lock)
        assert result.route == "shadow"

    def test_route_blocked_included_in_decision(self):
        lock = LiveTradingLock(enabled=False)
        result = self._decide("paused", lock)
        assert result.route == "blocked"


class TestComputeExecutionRoute:
    def test_paused_returns_blocked(self):
        assert compute_execution_route("paused") == "blocked"

    def test_paper_auto_returns_paper(self):
        assert compute_execution_route("paper_auto") == "paper"

    def test_live_shadow_returns_shadow(self):
        assert compute_execution_route("live_shadow") == "shadow"

    def test_live_small_auto_returns_blocked(self):
        assert compute_execution_route("live_small_auto") == "blocked"

    def test_unknown_returns_blocked(self):
        # Fail-closed for unknown mode
        assert compute_execution_route("unknown_mode") == "blocked"


class TestLiveTradingLock:
    def test_default_enabled_is_false(self):
        lock = LiveTradingLock()
        assert lock.enabled is False

    def test_custom_reason_is_stored(self):
        lock = LiveTradingLock(enabled=True, reason="upgrade")
        assert lock.enabled is True
        assert lock.reason == "upgrade"
