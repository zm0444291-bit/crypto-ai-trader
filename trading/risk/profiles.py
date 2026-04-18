from decimal import Decimal

from pydantic import BaseModel, Field


class RiskProfile(BaseModel):
    name: str
    equity_min_usdt: Decimal = Field(ge=Decimal("0"))
    equity_max_usdt: Decimal | None = Field(default=None, ge=Decimal("0"))
    daily_loss_caution_pct: Decimal = Field(gt=Decimal("0"))
    daily_loss_no_new_positions_pct: Decimal = Field(gt=Decimal("0"))
    daily_loss_global_pause_pct: Decimal = Field(gt=Decimal("0"))
    max_trade_risk_pct: Decimal = Field(gt=Decimal("0"))
    max_trade_risk_hard_cap_pct: Decimal = Field(gt=Decimal("0"))
    max_symbol_position_pct: Decimal = Field(gt=Decimal("0"))
    max_total_position_pct: Decimal = Field(gt=Decimal("0"))


def default_risk_profiles() -> list[RiskProfile]:
    return [
        RiskProfile(
            name="small_balanced",
            equity_min_usdt=Decimal("0"),
            equity_max_usdt=Decimal("1000"),
            daily_loss_caution_pct=Decimal("5"),
            daily_loss_no_new_positions_pct=Decimal("7"),
            daily_loss_global_pause_pct=Decimal("10"),
            max_trade_risk_pct=Decimal("1.5"),
            max_trade_risk_hard_cap_pct=Decimal("2.0"),
            max_symbol_position_pct=Decimal("30"),
            max_total_position_pct=Decimal("70"),
        ),
        RiskProfile(
            name="medium_conservative",
            equity_min_usdt=Decimal("1000"),
            equity_max_usdt=Decimal("10000"),
            daily_loss_caution_pct=Decimal("3"),
            daily_loss_no_new_positions_pct=Decimal("5"),
            daily_loss_global_pause_pct=Decimal("7"),
            max_trade_risk_pct=Decimal("1.0"),
            max_trade_risk_hard_cap_pct=Decimal("1.5"),
            max_symbol_position_pct=Decimal("25"),
            max_total_position_pct=Decimal("60"),
        ),
        RiskProfile(
            name="large_conservative",
            equity_min_usdt=Decimal("10000"),
            equity_max_usdt=None,
            daily_loss_caution_pct=Decimal("2"),
            daily_loss_no_new_positions_pct=Decimal("4"),
            daily_loss_global_pause_pct=Decimal("5"),
            max_trade_risk_pct=Decimal("0.5"),
            max_trade_risk_hard_cap_pct=Decimal("1.0"),
            max_symbol_position_pct=Decimal("20"),
            max_total_position_pct=Decimal("50"),
        ),
    ]


def select_risk_profile(
    equity_usdt: Decimal, profiles: list[RiskProfile] | None = None
) -> RiskProfile:
    if equity_usdt < Decimal("0"):
        raise ValueError("equity_usdt must be greater than or equal to zero")
    if profiles is None:
        profiles = default_risk_profiles()
    if not profiles:
        raise ValueError("profiles must not be empty")
    for profile in profiles:
        if equity_usdt >= profile.equity_min_usdt:
            if profile.equity_max_usdt is None or equity_usdt < profile.equity_max_usdt:
                return profile
    # Fallback to the last profile (largest tier) if nothing matches
    return profiles[-1]


def daily_pnl_pct(day_start_equity: Decimal, current_equity: Decimal) -> Decimal:
    if day_start_equity <= Decimal("0"):
        raise ValueError("day_start_equity must be greater than zero")
    return (current_equity - day_start_equity) / day_start_equity * Decimal("100")


def pct_to_amount(equity_usdt: Decimal, pct: Decimal) -> Decimal:
    if equity_usdt < Decimal("0"):
        raise ValueError("equity_usdt must be greater than or equal to zero")
    if pct < Decimal("0"):
        raise ValueError("pct must be greater than or equal to zero")
    return equity_usdt * pct / Decimal("100")
