from decimal import Decimal

from pydantic import BaseModel

from trading.risk.profiles import RiskProfile
from trading.risk.state import RiskState, classify_daily_loss
from trading.strategies.base import TradeCandidate


class PortfolioRiskSnapshot(BaseModel):
    account_equity: Decimal
    day_start_equity: Decimal
    total_position_pct: Decimal
    symbol_position_pct: Decimal
    open_positions: int
    daily_order_count: int
    symbol_daily_trade_count: int
    consecutive_losses: int
    data_is_fresh: bool
    kill_switch_enabled: bool


class PreTradeRiskDecision(BaseModel):
    approved: bool
    risk_state: RiskState
    size_multiplier: Decimal
    reject_reasons: list[str]


def evaluate_pre_trade_risk(
    candidate: TradeCandidate,
    snapshot: PortfolioRiskSnapshot,
    profile: RiskProfile,
    max_daily_orders: int = 15,
    max_symbol_daily_trades: int = 4,
    max_consecutive_losses: int = 4,
) -> PreTradeRiskDecision:
    reject_reasons: list[str] = []

    # Kill switch always rejects with emergency_stop
    if snapshot.kill_switch_enabled:
        return PreTradeRiskDecision(
            approved=False,
            risk_state="emergency_stop",
            size_multiplier=Decimal("0"),
            reject_reasons=["kill_switch_enabled"],
        )

    # Stale data always rejects
    if not snapshot.data_is_fresh:
        return PreTradeRiskDecision(
            approved=False,
            risk_state="no_new_positions",
            size_multiplier=Decimal("0"),
            reject_reasons=["stale_market_data"],
        )

    # Classify daily loss to determine risk state
    daily_loss_decision = classify_daily_loss(
        snapshot.day_start_equity,
        snapshot.account_equity,
        profile,
    )

    # Reject on no_new_positions or global_pause daily loss states
    if daily_loss_decision.risk_state in ("no_new_positions", "global_pause"):
        reject_reasons.append(f"daily_loss_{daily_loss_decision.risk_state}")
        return PreTradeRiskDecision(
            approved=False,
            risk_state=daily_loss_decision.risk_state,
            size_multiplier=Decimal("0"),
            reject_reasons=reject_reasons,
        )

    # Position limit checks
    if snapshot.total_position_pct >= profile.max_total_position_pct:
        reject_reasons.append("max_total_position_reached")

    if snapshot.symbol_position_pct >= profile.max_symbol_position_pct:
        reject_reasons.append("max_symbol_position_reached")

    # Order count checks
    if snapshot.daily_order_count >= max_daily_orders:
        reject_reasons.append("max_daily_orders_reached")

    if snapshot.symbol_daily_trade_count >= max_symbol_daily_trades:
        reject_reasons.append("max_symbol_daily_trades_reached")

    # Consecutive losses check
    if snapshot.consecutive_losses >= max_consecutive_losses:
        reject_reasons.append("max_consecutive_losses_reached")

    # If any reject reasons, return rejected decision
    if reject_reasons:
        return PreTradeRiskDecision(
            approved=False,
            risk_state="no_new_positions",
            size_multiplier=Decimal("0"),
            reject_reasons=reject_reasons,
        )

    # Approved: determine risk state and size multiplier from daily loss
    if daily_loss_decision.risk_state == "degraded":
        risk_state: RiskState = "degraded"
        size_multiplier = Decimal("0.5")
    else:
        risk_state = "normal"
        size_multiplier = Decimal("1")

    return PreTradeRiskDecision(
        approved=True,
        risk_state=risk_state,
        size_multiplier=size_multiplier,
        reject_reasons=[],
    )
