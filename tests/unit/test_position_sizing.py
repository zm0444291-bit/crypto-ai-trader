from datetime import UTC, datetime
from decimal import Decimal

from trading.risk.position_sizing import calculate_position_size
from trading.risk.pre_trade import PreTradeRiskDecision
from trading.risk.profiles import default_risk_profiles
from trading.strategies.base import TradeCandidate


def make_candidate(
    entry: Decimal = Decimal("100"),
    stop: Decimal = Decimal("96"),
) -> TradeCandidate:
    return TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=entry,
        stop_reference=stop,
        rule_confidence=Decimal("0.70"),
        reason="Momentum aligned.",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )


def approved_decision(size_multiplier: Decimal = Decimal("1")) -> PreTradeRiskDecision:
    return PreTradeRiskDecision(
        approved=True,
        risk_state="normal",
        size_multiplier=size_multiplier,
        reject_reasons=[],
    )


def test_calculates_notional_for_normal_approved_trade():
    profile = default_risk_profiles()[0]

    result = calculate_position_size(
        candidate=make_candidate(),
        pre_trade_decision=approved_decision(),
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is True
    assert result.max_loss_usdt == Decimal("7.5")
    assert result.notional_usdt == Decimal("150")
    assert result.reject_reasons == []


def test_applies_degraded_size_multiplier():
    profile = default_risk_profiles()[0]

    result = calculate_position_size(
        candidate=make_candidate(),
        pre_trade_decision=approved_decision(size_multiplier=Decimal("0.5")),
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is True
    assert result.notional_usdt == Decimal("93.75")


def test_caps_notional_by_symbol_position_limit():
    profile = default_risk_profiles()[0]

    result = calculate_position_size(
        candidate=make_candidate(entry=Decimal("100"), stop=Decimal("99")),
        pre_trade_decision=approved_decision(),
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is True
    assert result.notional_usdt == Decimal("150")


def test_rejects_when_pre_trade_rejected():
    profile = default_risk_profiles()[0]
    decision = PreTradeRiskDecision(
        approved=False,
        risk_state="no_new_positions",
        size_multiplier=Decimal("0"),
        reject_reasons=["stale_market_data"],
    )

    result = calculate_position_size(
        candidate=make_candidate(),
        pre_trade_decision=decision,
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is False
    assert result.notional_usdt == Decimal("0")
    assert result.max_loss_usdt == Decimal("0")
    assert "pre_trade_rejected" in result.reject_reasons


def test_rejects_invalid_stop_distance():
    profile = default_risk_profiles()[0]

    result = calculate_position_size(
        candidate=make_candidate(entry=Decimal("100"), stop=Decimal("100")),
        pre_trade_decision=approved_decision(),
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is False
    assert result.reject_reasons == ["invalid_stop_distance"]


def test_rejects_below_min_notional():
    profile = default_risk_profiles()[0]

    result = calculate_position_size(
        candidate=make_candidate(entry=Decimal("100"), stop=Decimal("50")),
        pre_trade_decision=approved_decision(),
        profile=profile,
        account_equity=Decimal("100"),
        min_notional_usdt=Decimal("50"),
    )

    assert result.approved is False
    assert result.reject_reasons == ["below_min_notional"]


def test_hard_cap_prevents_max_loss_exceeding_hard_cap():
    profile = default_risk_profiles()[0].model_copy(update={"max_trade_risk_pct": Decimal("5")})

    result = calculate_position_size(
        candidate=make_candidate(),
        pre_trade_decision=approved_decision(),
        profile=profile,
        account_equity=Decimal("500"),
    )

    assert result.approved is True
    assert result.max_loss_usdt == Decimal("10.0")
