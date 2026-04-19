"""Runtime mode state model with strict transition rules."""

from __future__ import annotations

from pydantic import BaseModel

from trading.execution.gate import TRADE_MODES


class ModeTransitionResult(BaseModel):
    """Result of a mode transition validation."""

    allowed: bool
    reason: str


def validate_mode_transition(
    from_mode: TRADE_MODES,
    to_mode: TRADE_MODES,
    lock_enabled: bool = False,
    allow_live_unlock: bool = False,
) -> ModeTransitionResult:
    """Validate a transition between trade modes.

    Rules:
    - No direct paused -> live_small_auto
    - No paper_auto -> live_small_auto without passing through live_shadow
    - live_small_auto requires explicit unlock flag + lock enabled

    Args:
        from_mode: Current mode.
        to_mode: Desired target mode.
        lock_enabled: Whether the live trading lock is currently enabled.
        allow_live_unlock: Whether explicit live unlock has been granted.

    Returns:
        ModeTransitionResult with allowed flag and reason.
    """
    # Same mode — always allowed
    if from_mode == to_mode:
        return ModeTransitionResult(allowed=True, reason="same_mode")

    # No direct paused -> live_small_auto
    if from_mode == "paused" and to_mode == "live_small_auto":
        return ModeTransitionResult(
            allowed=False,
            reason="blocked: cannot transition directly from paused to live_small_auto",
        )

    # No paper_auto -> live_small_auto without live_shadow first
    if from_mode == "paper_auto" and to_mode == "live_small_auto":
        return ModeTransitionResult(
            allowed=False,
            reason="blocked: must transition through live_shadow first",
        )

    # live_small_auto requires explicit unlock + lock enabled
    if to_mode == "live_small_auto":
        if not allow_live_unlock:
            return ModeTransitionResult(
                allowed=False,
                reason="blocked: live_small_auto requires explicit unlock",
            )
        if not lock_enabled:
            return ModeTransitionResult(
                allowed=False,
                reason="blocked: live_small_auto requires live_trading_lock enabled",
            )
        return ModeTransitionResult(
            allowed=True,
            reason="live_small_auto_unlocked",
        )

    # All other transitions are allowed
    return ModeTransitionResult(allowed=True, reason="transition_allowed")
