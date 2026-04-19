from decimal import Decimal

from pydantic import BaseModel

from trading.risk.pre_trade import PreTradeRiskDecision
from trading.risk.profiles import RiskProfile
from trading.strategies.base import TradeCandidate


class PositionSizeResult(BaseModel):
    approved: bool
    notional_usdt: Decimal
    max_loss_usdt: Decimal
    reject_reasons: list[str]


def calculate_position_size(
    candidate: TradeCandidate,
    pre_trade_decision: PreTradeRiskDecision,
    profile: RiskProfile,
    account_equity: Decimal,
    min_notional_usdt: Decimal = Decimal("10"),
) -> PositionSizeResult:
    if not pre_trade_decision.approved:
        return PositionSizeResult(
            approved=False,
            notional_usdt=Decimal("0"),
            max_loss_usdt=Decimal("0"),
            reject_reasons=["pre_trade_rejected", *pre_trade_decision.reject_reasons],
        )

    stop_distance = candidate.entry_reference - candidate.stop_reference
    if stop_distance <= Decimal("0"):
        return PositionSizeResult(
            approved=False,
            notional_usdt=Decimal("0"),
            max_loss_usdt=Decimal("0"),
            reject_reasons=["invalid_stop_distance"],
        )

    target_loss = account_equity * profile.max_trade_risk_pct / Decimal("100")
    hard_cap_loss = account_equity * profile.max_trade_risk_hard_cap_pct / Decimal("100")
    max_loss_usdt = min(target_loss, hard_cap_loss)

    loss_fraction = stop_distance / candidate.entry_reference
    raw_notional = max_loss_usdt / loss_fraction
    adjusted_notional = raw_notional * pre_trade_decision.size_multiplier
    symbol_cap = account_equity * profile.max_symbol_position_pct / Decimal("100")
    final_notional = min(adjusted_notional, symbol_cap)

    if final_notional < min_notional_usdt:
        return PositionSizeResult(
            approved=False,
            notional_usdt=Decimal("0"),
            max_loss_usdt=max_loss_usdt,
            reject_reasons=["below_min_notional"],
        )

    return PositionSizeResult(
        approved=True,
        notional_usdt=final_notional,
        max_loss_usdt=max_loss_usdt,
        reject_reasons=[],
    )
