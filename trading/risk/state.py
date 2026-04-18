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
