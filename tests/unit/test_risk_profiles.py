from decimal import Decimal

import pytest

from trading.risk.profiles import (
    daily_pnl_pct,
    default_risk_profiles,
    pct_to_amount,
    select_risk_profile,
)


class TestDefaultRiskProfiles:
    def test_returns_three_profiles(self):
        profiles = default_risk_profiles()
        assert len(profiles) == 3

    def test_small_balanced_profile(self):
        profile = next(p for p in default_risk_profiles() if p.name == "small_balanced")
        assert profile.equity_min_usdt == Decimal("0")
        assert profile.equity_max_usdt == Decimal("1000")
        assert profile.daily_loss_caution_pct == Decimal("5")
        assert profile.daily_loss_no_new_positions_pct == Decimal("7")
        assert profile.daily_loss_global_pause_pct == Decimal("10")
        assert profile.max_trade_risk_pct == Decimal("1.5")
        assert profile.max_trade_risk_hard_cap_pct == Decimal("2.0")
        assert profile.max_symbol_position_pct == Decimal("30")
        assert profile.max_total_position_pct == Decimal("70")

    def test_medium_conservative_profile(self):
        profile = next(p for p in default_risk_profiles() if p.name == "medium_conservative")
        assert profile.equity_min_usdt == Decimal("1000")
        assert profile.equity_max_usdt == Decimal("10000")
        assert profile.daily_loss_caution_pct == Decimal("3")
        assert profile.daily_loss_no_new_positions_pct == Decimal("5")
        assert profile.daily_loss_global_pause_pct == Decimal("7")
        assert profile.max_trade_risk_pct == Decimal("1.0")
        assert profile.max_trade_risk_hard_cap_pct == Decimal("1.5")
        assert profile.max_symbol_position_pct == Decimal("25")
        assert profile.max_total_position_pct == Decimal("60")

    def test_large_conservative_profile(self):
        profile = next(p for p in default_risk_profiles() if p.name == "large_conservative")
        assert profile.equity_min_usdt == Decimal("10000")
        assert profile.equity_max_usdt is None
        assert profile.daily_loss_caution_pct == Decimal("2")
        assert profile.daily_loss_no_new_positions_pct == Decimal("4")
        assert profile.daily_loss_global_pause_pct == Decimal("5")
        assert profile.max_trade_risk_pct == Decimal("0.5")
        assert profile.max_trade_risk_hard_cap_pct == Decimal("1.0")
        assert profile.max_symbol_position_pct == Decimal("20")
        assert profile.max_total_position_pct == Decimal("50")


class TestSelectRiskProfile:
    def test_500_usdt_returns_small_balanced(self):
        profile = select_risk_profile(Decimal("500"))
        assert profile.name == "small_balanced"

    def test_2000_usdt_returns_medium_conservative(self):
        profile = select_risk_profile(Decimal("2000"))
        assert profile.name == "medium_conservative"

    def test_20000_usdt_returns_large_conservative(self):
        profile = select_risk_profile(Decimal("20000"))
        assert profile.name == "large_conservative"

    def test_boundary_1000_usdt_returns_medium_conservative(self):
        profile = select_risk_profile(Decimal("1000"))
        assert profile.name == "medium_conservative"

    def test_boundary_999_usdt_returns_small_balanced(self):
        profile = select_risk_profile(Decimal("999"))
        assert profile.name == "small_balanced"

    def test_boundary_10000_usdt_returns_large_conservative(self):
        profile = select_risk_profile(Decimal("10000"))
        assert profile.name == "large_conservative"


class TestDailyPnlPct:
    def test_calculates_positive_gain(self):
        result = daily_pnl_pct(Decimal("100"), Decimal("105"))
        assert result == Decimal("5")

    def test_calculates_negative_loss(self):
        result = daily_pnl_pct(Decimal("100"), Decimal("95"))
        assert result == Decimal("-5")

    def test_calculates_zero_change(self):
        result = daily_pnl_pct(Decimal("100"), Decimal("100"))
        assert result == Decimal("0")

    def test_raises_error_on_zero_day_start_equity(self):
        with pytest.raises(ValueError, match="day_start_equity must be greater than zero"):
            daily_pnl_pct(Decimal("0"), Decimal("95"))

    def test_raises_error_on_negative_day_start_equity(self):
        with pytest.raises(ValueError, match="day_start_equity must be greater than zero"):
            daily_pnl_pct(Decimal("-100"), Decimal("95"))


class TestPctToAmount:
    def test_converts_percentage_to_amount(self):
        result = pct_to_amount(Decimal("500"), Decimal("7"))
        assert result == Decimal("35")

    def test_converts_small_percentage(self):
        result = pct_to_amount(Decimal("1000"), Decimal("1.5"))
        assert result == Decimal("15")

    def test_converts_zero_percentage(self):
        result = pct_to_amount(Decimal("1000"), Decimal("0"))
        assert result == Decimal("0")
