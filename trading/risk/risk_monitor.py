"""Real-time risk monitoring: equity drawdown, position limits, order counts.

Emits risk_state_changed events via the dashboard WS broadcast so the frontend
sees risk state transitions instantly without polling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading.dashboard_api.ws_manager import Channel, broadcast_from_sync
from trading.risk.profiles import RiskProfile, select_risk_profile
from trading.risk.state import RiskState, classify_daily_loss

logger = logging.getLogger(__name__)


class RiskEventType(StrEnum):
    RISK_STATE_CHANGED = "risk_state_changed"
    EQUITY_ALERT = "equity_alert"
    POSITION_LIMIT_WARNING = "position_limit_warning"


@dataclass
class RiskAlert:
    event_type: RiskEventType
    risk_state: RiskState
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class RiskMonitor:
    """Monitor account equity and risk metrics in real-time.

    Accepts equity snapshots from the trading cycle and evaluates risk state.
    Broadcasts state changes to the dashboard WS.
    """

    def __init__(self, day_start_equity: Decimal) -> None:
        self._day_start_equity = day_start_equity
        self._current_equity = day_start_equity
        self._profile: RiskProfile = select_risk_profile(day_start_equity)
        self._current_state: RiskState = "normal"
        self._last_broadcast: str | None = None

    # ── Snapshot update ─────────────────────────────────────────────────────

    def update_equity(self, equity: Decimal) -> None:
        """Update current equity and re-evaluate risk state."""
        self._current_equity = equity
        self._profile = select_risk_profile(equity)
        self._evaluate()

    # ── Internal evaluation ─────────────────────────────────────────────────

    def _evaluate(self) -> None:
        """Evaluate risk state and broadcast on transitions."""
        decision = classify_daily_loss(
            self._day_start_equity,
            self._current_equity,
            self._profile,
        )
        new_state = decision.risk_state

        if new_state == self._current_state:
            return  # No state change

        old_state = self._current_state
        self._current_state = new_state

        # Build alert message
        msg = (
            f"Risk state: {old_state} → {new_state}  "
            f"daily_pnl={decision.daily_pnl_pct:.2f}%  reason={decision.reason}"
        )
        alert = RiskAlert(
            event_type=RiskEventType.RISK_STATE_CHANGED,
            risk_state=new_state,
            message=msg,
            details={
                "old_state": old_state,
                "new_state": new_state,
                "daily_pnl_pct": str(decision.daily_pnl_pct),
                "current_equity_usdt": str(self._current_equity),
                "day_start_equity_usdt": str(self._day_start_equity),
                "profile": self._profile.name,
            },
        )
        self._broadcast(alert)

    def _broadcast(self, alert: RiskAlert) -> None:
        """Bridge alert to dashboard WS from synchronous context."""
        payload = {
            "type": "risk_update",
            "data": {
                "event_type": alert.event_type,
                "risk_state": alert.risk_state,
                "message": alert.message,
                "details": alert.details,
                "timestamp": alert.timestamp,
            },
        }
        try:
            broadcast_from_sync(Channel.RISK, "risk_update", payload)
        except Exception as exc:  # pragma: no cover — WS errors must not crash trading
            logger.warning("Failed to broadcast risk alert: %s", exc)

    # ── Query ───────────────────────────────────────────────────────────────

    @property
    def risk_state(self) -> RiskState:
        return self._current_state

    @property
    def profile(self) -> RiskProfile:
        return self._profile

    @property
    def current_equity(self) -> Decimal:
        return self._current_equity

    @property
    def day_start_equity(self) -> Decimal:
        return self._day_start_equity

    @property
    def daily_pnl_pct(self) -> Decimal:
        if self._day_start_equity <= Decimal("0"):
            return Decimal("0")
        return (
            (self._current_equity - self._day_start_equity)
            / self._day_start_equity
            * Decimal("100")
        )

    # ── Per-symbol limit tracking ───────────────────────────────────────────

    def check_position_limits(
        self,
        total_position_pct: Decimal,
        symbol_position_pct: Decimal,
        symbol: str,
    ) -> list[str]:
        """Return list of warnings when position limits are near (>= 80%)."""
        warnings: list[str] = []
        threshold = Decimal("0.8")
        if total_position_pct >= self._profile.max_total_position_pct * threshold:
            warnings.append(
                f"Total position {total_position_pct:.1f}% >= 80% of limit "
                f"({self._profile.max_total_position_pct}%)"
            )
        if symbol_position_pct >= self._profile.max_symbol_position_pct * threshold:
            warnings.append(
                f"Symbol {symbol} position {symbol_position_pct:.1f}% >= 80% of limit "
                f"({self._profile.max_symbol_position_pct}%)"
            )
        return warnings

    def check_equity_alert(self) -> RiskAlert | None:
        """Return an equity alert if current equity is below all thresholds."""
        decision = classify_daily_loss(
            self._day_start_equity,
            self._current_equity,
            self._profile,
        )
        if decision.risk_state in ("degraded", "no_new_positions", "global_pause"):
            return RiskAlert(
                event_type=RiskEventType.EQUITY_ALERT,
                risk_state=decision.risk_state,
                message=(
                    f"Equity alert: daily_pnl={decision.daily_pnl_pct:.2f}%  "
                    f"reason={decision.reason}  "
                    f"profile={self._profile.name}"
                ),
                details={
                    "daily_pnl_pct": str(decision.daily_pnl_pct),
                    "current_equity_usdt": str(self._current_equity),
                    "day_start_equity_usdt": str(self._day_start_equity),
                    "profile": self._profile.name,
                    "reason": decision.reason,
                },
            )
        return None
