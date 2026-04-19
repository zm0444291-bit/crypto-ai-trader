"""Execution Gate — mode-aware routing decision between strategy/risk and executors."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TRADE_MODES = Literal["paused", "paper_auto", "live_shadow", "live_small_auto"]


class ExecutionDecision(BaseModel):
    """Structured decision from the ExecutionGate."""

    allowed: bool
    route: Literal["paper", "shadow", "blocked"]
    reason: str
    mode: TRADE_MODES


class LiveTradingLock(BaseModel):
    """Hard lock preventing accidental live routing.

    Attributes:
        enabled: Whether the live trading lock is active. Defaults to False.
        reason: Optional explanation for why the lock is engaged.
    """

    enabled: bool = False
    reason: str | None = None


class ExecutionGate:
    """Mode-aware routing decision gate.

    Sits between the strategy/risk output and the executors, enforcing
    trade mode and live trading lock before any order is routed.
    """

    def decide(
        self,
        mode: TRADE_MODES,
        lock: LiveTradingLock,
        risk_approved: bool,
        kill_switch_enabled: bool,
        candidate_symbol: str | None = None,
    ) -> ExecutionDecision:
        """Evaluate whether a candidate/order should be executed.

        Args:
            mode: Current trade mode.
            lock: Current live trading lock state.
            risk_approved: Whether the RiskEngine approved the trade.
            kill_switch_enabled: Whether the global kill switch is active.
            candidate_symbol: Symbol for context in error messages.

        Returns:
            ExecutionDecision with allowed flag, route, reason, and mode.
        """
        # Emergency: kill switch always blocks
        if kill_switch_enabled:
            return ExecutionDecision(
                allowed=False,
                route="blocked",
                reason="kill_switch_active",
                mode=mode,
            )

        # Lock blocks only live-routing modes; paper mode remains available.
        if lock.enabled and mode in {"live_shadow", "live_small_auto"}:
            return ExecutionDecision(
                allowed=False,
                route="blocked",
                reason=lock.reason or "live_trading_lock_enabled",
                mode=mode,
            )

        # Mode-based routing
        if mode == "paused":
            return ExecutionDecision(
                allowed=False,
                route="blocked",
                reason="mode_paused",
                mode=mode,
            )

        if mode == "paper_auto":
            if not risk_approved:
                return ExecutionDecision(
                    allowed=False,
                    route="blocked",
                    reason="risk_rejected",
                    mode=mode,
                )
            return ExecutionDecision(
                allowed=True,
                route="paper",
                reason="paper_auto_approved",
                mode=mode,
            )

        if mode == "live_shadow":
            return ExecutionDecision(
                allowed=True,
                route="shadow",
                reason="live_shadow_approved",
                mode=mode,
            )

        if mode == "live_small_auto":
            # Blocked by default in this milestone — no live execution yet
            return ExecutionDecision(
                allowed=False,
                route="blocked",
                reason="live_small_auto_requires_explicit_unlock",
                mode=mode,
            )

        # Unknown mode — fail closed
        return ExecutionDecision(
            allowed=False,
            route="blocked",
            reason=f"unknown_mode:{mode}",
            mode=mode,
        )


def compute_execution_route(mode: TRADE_MODES) -> Literal["paper", "shadow", "blocked"]:
    """Return the effective execution route for a given mode (no risk evaluation)."""
    if mode == "paused":
        return "blocked"
    if mode == "paper_auto":
        return "paper"
    if mode == "live_shadow":
        return "shadow"
    if mode == "live_small_auto":
        return "blocked"
    return "blocked"
