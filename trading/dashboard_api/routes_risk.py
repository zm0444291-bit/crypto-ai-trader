from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trading.risk.profiles import RiskProfile, pct_to_amount, select_risk_profile
from trading.risk.state import RiskState, classify_daily_loss

router = APIRouter(tags=["risk"])


def _plain_decimal(value: Decimal) -> Decimal:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return normalized.quantize(Decimal("1"))
    return normalized


class RiskThresholdSummary(BaseModel):
    pct: Decimal
    amount_usdt: Decimal


class RiskThresholdsResponse(BaseModel):
    caution: RiskThresholdSummary
    no_new_positions: RiskThresholdSummary
    global_pause: RiskThresholdSummary


class RiskProfileSummary(BaseModel):
    name: str
    equity_min_usdt: Decimal
    equity_max_usdt: Decimal | None
    max_trade_risk_pct: Decimal
    max_trade_risk_hard_cap_pct: Decimal
    max_symbol_position_pct: Decimal
    max_total_position_pct: Decimal


class RiskStatusResponse(BaseModel):
    day_start_equity: Decimal
    current_equity: Decimal
    risk_profile: RiskProfileSummary
    risk_state: RiskState
    daily_pnl_pct: Decimal
    thresholds: RiskThresholdsResponse
    max_trade_risk_usdt: Decimal
    max_trade_risk_hard_cap_usdt: Decimal
    max_symbol_position_usdt: Decimal
    max_total_position_usdt: Decimal
    reason: str


def _profile_summary(profile: RiskProfile) -> RiskProfileSummary:
    return RiskProfileSummary(
        name=profile.name,
        equity_min_usdt=profile.equity_min_usdt,
        equity_max_usdt=profile.equity_max_usdt,
        max_trade_risk_pct=profile.max_trade_risk_pct,
        max_trade_risk_hard_cap_pct=profile.max_trade_risk_hard_cap_pct,
        max_symbol_position_pct=profile.max_symbol_position_pct,
        max_total_position_pct=profile.max_total_position_pct,
    )


def _daily_thresholds(
    day_start_equity: Decimal, profile: RiskProfile
) -> RiskThresholdsResponse:
    return RiskThresholdsResponse(
        caution=RiskThresholdSummary(
            pct=_plain_decimal(profile.daily_loss_caution_pct),
            amount_usdt=_plain_decimal(
                pct_to_amount(day_start_equity, profile.daily_loss_caution_pct)
            ),
        ),
        no_new_positions=RiskThresholdSummary(
            pct=_plain_decimal(profile.daily_loss_no_new_positions_pct),
            amount_usdt=_plain_decimal(
                pct_to_amount(day_start_equity, profile.daily_loss_no_new_positions_pct)
            ),
        ),
        global_pause=RiskThresholdSummary(
            pct=_plain_decimal(profile.daily_loss_global_pause_pct),
            amount_usdt=_plain_decimal(
                pct_to_amount(day_start_equity, profile.daily_loss_global_pause_pct)
            ),
        ),
    )


@router.get("/risk/status", response_model=RiskStatusResponse)
def read_risk_status(
    day_start_equity: Decimal = Decimal("500"),
    current_equity: Decimal = Decimal("500"),
) -> RiskStatusResponse:
    try:
        profile = select_risk_profile(current_equity)
        daily_loss_decision = classify_daily_loss(
            day_start_equity=day_start_equity,
            current_equity=current_equity,
            profile=profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RiskStatusResponse(
        day_start_equity=day_start_equity,
        current_equity=current_equity,
        risk_profile=_profile_summary(profile),
        risk_state=daily_loss_decision.risk_state,
        daily_pnl_pct=_plain_decimal(daily_loss_decision.daily_pnl_pct),
        thresholds=_daily_thresholds(day_start_equity, profile),
        max_trade_risk_usdt=_plain_decimal(
            pct_to_amount(current_equity, profile.max_trade_risk_pct)
        ),
        max_trade_risk_hard_cap_usdt=_plain_decimal(
            pct_to_amount(current_equity, profile.max_trade_risk_hard_cap_pct)
        ),
        max_symbol_position_usdt=_plain_decimal(
            pct_to_amount(current_equity, profile.max_symbol_position_pct)
        ),
        max_total_position_usdt=_plain_decimal(
            pct_to_amount(current_equity, profile.max_total_position_pct)
        ),
        reason=daily_loss_decision.reason,
    )
