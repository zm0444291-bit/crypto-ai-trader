"""Unit tests for runtime mode transition validation."""

from trading.runtime.mode import validate_mode_transition


class TestValidateModeTransition:
    # ── same mode ──────────────────────────────────────────────────────────────

    def test_same_mode_allowed(self):
        for mode in ("paused", "paper_auto", "live_shadow", "live_small_auto"):
            result = validate_mode_transition(mode, mode)
            assert result.allowed is True
            assert result.reason == "same_mode"

    # ── paused transitions ────────────────────────────────────────────────────

    def test_paused_to_paper_auto_allowed(self):
        result = validate_mode_transition("paused", "paper_auto")
        assert result.allowed is True

    def test_paused_to_live_shadow_allowed(self):
        result = validate_mode_transition("paused", "live_shadow")
        assert result.allowed is True

    def test_paused_to_live_small_auto_blocked(self):
        result = validate_mode_transition("paused", "live_small_auto")
        assert result.allowed is False
        assert "paused" in result.reason
        assert "live_small_auto" in result.reason

    # ── paper_auto transitions ─────────────────────────────────────────────────

    def test_paper_auto_to_live_shadow_allowed(self):
        result = validate_mode_transition("paper_auto", "live_shadow")
        assert result.allowed is True

    def test_paper_auto_to_live_small_auto_blocked(self):
        result = validate_mode_transition("paper_auto", "live_small_auto")
        assert result.allowed is False
        assert "live_shadow" in result.reason

    def test_paper_auto_to_paused_allowed(self):
        result = validate_mode_transition("paper_auto", "paused")
        assert result.allowed is True

    # ── live_shadow transitions ─────────────────────────────────────────────────

    def test_live_shadow_to_live_small_auto_blocked_without_unlock(self):
        result = validate_mode_transition("live_shadow", "live_small_auto")
        assert result.allowed is False
        assert "unlock" in result.reason

    def test_live_shadow_to_live_small_auto_blocked_without_lock(self):
        result = validate_mode_transition(
            "live_shadow", "live_small_auto", lock_enabled=False, allow_live_unlock=True
        )
        assert result.allowed is False
        assert "lock" in result.reason

    def test_live_shadow_to_live_small_auto_allowed_with_unlock_and_lock(self):
        result = validate_mode_transition(
            "live_shadow", "live_small_auto", lock_enabled=True, allow_live_unlock=True
        )
        assert result.allowed is True
        assert result.reason == "live_small_auto_unlocked"

    def test_live_shadow_to_paper_auto_allowed(self):
        result = validate_mode_transition("live_shadow", "paper_auto")
        assert result.allowed is True

    # ── live_small_auto transitions ────────────────────────────────────────────

    def test_live_small_auto_to_paper_auto_allowed(self):
        # Exiting live mode back to paper is allowed without unlock ceremony.
        result = validate_mode_transition("live_small_auto", "paper_auto")
        assert result.allowed is True

    # ── all other transitions allowed ─────────────────────────────────────────

    def test_live_shadow_to_paused_allowed(self):
        result = validate_mode_transition("live_shadow", "paused")
        assert result.allowed is True

    def test_paper_auto_to_live_shadow_allowed_path(self):
        # The required path: paper_auto -> live_shadow -> live_small_auto
        step1 = validate_mode_transition("paper_auto", "live_shadow")
        assert step1.allowed is True
        step2 = validate_mode_transition(
            "live_shadow", "live_small_auto", lock_enabled=True, allow_live_unlock=True
        )
        assert step2.allowed is True


class TestModeTransitionResult:
    def test_result_has_allowed_and_reason(self):
        result = validate_mode_transition("paused", "paper_auto")
        assert isinstance(result.allowed, bool)
        assert isinstance(result.reason, str)

    def test_blocked_result_has_explanation(self):
        result = validate_mode_transition("paused", "live_small_auto")
        assert result.allowed is False
        assert len(result.reason) > 0
