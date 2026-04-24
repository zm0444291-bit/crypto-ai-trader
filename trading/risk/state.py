from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from trading.risk.profiles import RiskProfile, daily_pnl_pct

RiskState = Literal["normal", "degraded", "no_new_positions", "global_pause", "emergency_stop"]


class DailyLossDecision(BaseModel):
    risk_state: RiskState
    daily_pnl_pct: Decimal
    reason: str


def classify_daily_loss(
    day_start_equity: Decimal, current_equity: Decimal, profile: RiskProfile
) -> DailyLossDecision:
    loss_pct = -daily_pnl_pct(day_start_equity, current_equity)

    if loss_pct >= profile.daily_loss_global_pause_pct:
        return DailyLossDecision(
            risk_state="global_pause",
            daily_pnl_pct=-(loss_pct),
            reason=(
                f"Daily loss {loss_pct:.2f}% >= global pause "
                f"threshold {profile.daily_loss_global_pause_pct}%"
            ),
        )
    if loss_pct >= profile.daily_loss_no_new_positions_pct:
        return DailyLossDecision(
            risk_state="no_new_positions",
            daily_pnl_pct=-(loss_pct),
            reason=(
                f"Daily loss {loss_pct:.2f}% >= no-new-positions "
                f"threshold {profile.daily_loss_no_new_positions_pct}%"
            ),
        )
    if loss_pct >= profile.daily_loss_caution_pct:
        return DailyLossDecision(
            risk_state="degraded",
            daily_pnl_pct=-(loss_pct),
            reason=(
                f"Daily loss {loss_pct:.2f}% >= caution "
                f"threshold {profile.daily_loss_caution_pct}%"
            ),
        )
    return DailyLossDecision(
        risk_state="normal",
        daily_pnl_pct=-(loss_pct),
        reason=f"Daily loss {loss_pct:.2f}% within normal range",
    )


# ── Per-symbol consecutive loss tracker ───────────────────────────────────────


class ConsecutiveLossTracker:
    """Per-symbol streak tracker for loss/win isolation.

    Consecutive losses are tracked independently per symbol so that
    a BTCUSDT losing streak does not affect ETHUSDT.
    """

    def __init__(self) -> None:
        self._losses: dict[str, int] = {}

    # -- Mutation -----------------------------------------------------------

    def record_loss(self, symbol: str) -> None:
        """Increment the consecutive loss count for *symbol*."""
        self._losses[symbol] = self._losses.get(symbol, 0) + 1

    def record_win(self, symbol: str) -> None:
        """Reset the consecutive loss count for *symbol* only."""
        self._losses[symbol] = 0

    # -- Query -------------------------------------------------------------

    def get_consecutive_losses(self, symbol: str) -> int:
        """Return the consecutive loss count for *symbol* (0 if never recorded)."""
        return self._losses.get(symbol, 0)

    # -- Serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, int]:
        """Serialize to a plain dict (for JSON / DB storage)."""
        return dict(self._losses)

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "ConsecutiveLossTracker":
        """Reconstruct a tracker from a serialised dict.

        Accepts legacy integer values (where the tracker was global) for
        backward compatibility — they are stored under the empty-string key.
        """
        tracker = cls()
        if not data:
            return tracker
        # Detect legacy format: top-level keys are NOT symbols (e.g. integer key "3")
        # vs new format where keys are symbol strings.
        # We treat any key that looks like a valid symbol (alphanumeric+USDT/USDC)
        # as the new format; otherwise fall back to treating the value as a legacy
        # global count stored under the empty string.
        for k, v in data.items():
            if k in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT"):
                tracker._losses[k] = v
            elif k == "":
                # Legacy global integer — silently ignore; start fresh.
                pass
        return tracker
