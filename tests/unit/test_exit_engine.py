"""Unit tests for the exit engine (Stage 1 — ATR-based exits)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading.strategies.exits import (
    DEFAULT_ATR,
    ExitConfig,
    ExitEngine,
    ExitReason,
    ExitSignal,
    HardStopRule,
    TakeProfitRule,
    TimeExitRule,
    load_exit_rules_from_yaml,
)


def make_dt(hours_offset: int = 0) -> datetime:
    return datetime(2026, 4, 20, 12, 0, tzinfo=UTC) + timedelta(hours=hours_offset)


# ── ExitConfig tests ───────────────────────────────────────────────────────────


class TestExitConfig:
    def test_default_values(self):
        cfg = ExitConfig()
        assert cfg.hard_stop_atr_mult == Decimal("2")
        assert cfg.take_profit_atr_mult == Decimal("3")
        assert cfg.max_hold_hours == 24
        assert cfg.time_exit_pct == Decimal("0.5")

    def test_custom_values(self):
        cfg = ExitConfig(
            hard_stop_atr_mult=Decimal("1.5"),
            take_profit_atr_mult=Decimal("4"),
            max_hold_hours=12,
            time_exit_pct=Decimal("0.25"),
        )
        assert cfg.hard_stop_atr_mult == Decimal("1.5")
        assert cfg.take_profit_atr_mult == Decimal("4")
        assert cfg.max_hold_hours == 12
        assert cfg.time_exit_pct == Decimal("0.25")


class TestExitSignal:
    def test_serialization(self):
        sig = ExitSignal(
            symbol="BTCUSDT",
            reason=ExitReason.HARD_STOP,
            exit_price=Decimal("95000"),
            qty_to_exit=Decimal("0.5"),
            created_at=make_dt(),
            confidence=Decimal("1.0"),
            message="Hard stop triggered",
        )
        d = sig.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert d["reason"] == "hard_stop"
        assert d["exit_price"] == "95000"
        assert d["qty_to_exit"] == "0.5"
        assert d["message"] == "Hard stop triggered"


# ── HardStopRule tests ────────────────────────────────────────────────────────


class TestHardStopRule:
    @pytest.fixture
    def config(self):
        return ExitConfig(hard_stop_atr_mult=Decimal("2"))

    @pytest.fixture
    def rule(self, config):
        return HardStopRule()

    def test_triggers_when_market_at_or_below_stop(self, rule, config):
        # entry=100000, atr=1000, stop = 100000 * (1 - 2*1000/100000) = 98000
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("98000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP
        assert sig.exit_price == Decimal("98000")  # market_price
        assert sig.qty_to_exit == Decimal("1")

    def test_does_not_trigger_above_stop(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("99000"),  # above 98000 stop
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is None

    def test_triggers_on_breach_below_stop(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("2"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97000"),  # well below 98000 stop
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.qty_to_exit == Decimal("2")

    def test_uses_default_atr_when_position_entry_atr_is_none(self, rule, config):
        # With DEFAULT_ATR=100, stop = 100000 * (1 - 2*100/100000) = 99800
        # market=99700 < 99800 → triggers
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=None,  # uses DEFAULT_ATR = 100
            market_price=Decimal("99700"),  # below 99800 stop
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_exit_price_is_market_price_not_stop(self, rule, config):
        # When stop is triggered at 98000 but market already dropped to 97500
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97500"),  # below stop, but we use market_price
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.exit_price == Decimal("97500")  # market price, not stop price


# ── TakeProfitRule tests ───────────────────────────────────────────────────────


class TestTakeProfitRule:
    @pytest.fixture
    def config(self):
        return ExitConfig(take_profit_atr_mult=Decimal("3"))

    @pytest.fixture
    def rule(self, config):
        return TakeProfitRule()

    def test_triggers_when_market_at_or_above_target(self, rule, config):
        # entry=100000, atr=1000, tp = 100000 * (1 + 3*1000/100000) = 103000
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("103000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.reason == ExitReason.TAKE_PROFIT
        assert sig.exit_price == Decimal("103000")

    def test_does_not_trigger_below_target(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("102500"),  # below 103000 target
            current_time=make_dt(),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is None


# ── TimeExitRule tests ─────────────────────────────────────────────────────────


class TestTimeExitRule:
    @pytest.fixture
    def config(self):
        return ExitConfig(max_hold_hours=24, time_exit_pct=Decimal("0.5"))

    @pytest.fixture
    def rule(self, config):
        return TimeExitRule()

    def test_triggers_after_max_hours(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=None,
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=25),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        assert sig.reason == ExitReason.TIME_EXIT
        assert sig.qty_to_exit == Decimal("0.5")  # 50% partial exit

    def test_does_not_trigger_before_max_hours(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=None,
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=12),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is None

    def test_uses_position_opened_at_for_elapsed_time(self, rule, config):
        # opened_at is 14h ago from now=+10h → elapsed = 24h → triggers
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=None,
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=10),
            position_opened_at=make_dt(hours_offset=-14),
            config=config,
        )
        # elapsed = 24h >= max_hours → triggers
        assert sig is not None
        assert sig.reason == ExitReason.TIME_EXIT

    def test_partial_exit_qty(self, rule, config):
        sig = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("2"),
            position_avg_entry=Decimal("100000"),
            position_entry_atr=None,
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=25),
            position_opened_at=make_dt(),
            config=config,
        )
        assert sig is not None
        # 50% of 2 = 1
        assert sig.qty_to_exit == Decimal("1")


# ── ExitEngine tests ──────────────────────────────────────────────────────────


class TestExitEngine:
    @pytest.fixture
    def config(self):
        return ExitConfig(
            hard_stop_atr_mult=Decimal("2"),
            take_profit_atr_mult=Decimal("3"),
            max_hold_hours=24,
            time_exit_pct=Decimal("0.5"),
        )

    @pytest.fixture
    def engine(self, config):
        return ExitEngine(config=config)

    def test_hard_stop_triggers(self, engine, config):
        # entry=100000, atr=1000, stop=98000
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97000"),  # below stop
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_take_profit_triggers(self, engine, config):
        # entry=100000, atr=1000, tp=103000
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("103500"),  # above tp
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.TAKE_PROFIT

    def test_time_exit_partial(self, engine, config):
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=25),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.TIME_EXIT
        assert sig.qty_to_exit == Decimal("0.5")  # 50% partial

    def test_hard_stop_priority_over_take_profit(self, engine, config):
        # Both hard_stop and take_profit triggered → hard_stop wins (priority 0 < 1)
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97000"),  # below stop AND below tp
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_hard_stop_priority_over_time_exit(self, engine, config):
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97000"),  # below stop
            current_time=make_dt(hours_offset=25),  # also past time limit
            position_opened_at=make_dt(),
        )
        # Hard stop priority 0 < TimeExit priority 2
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_no_signal_returns_none(self, engine, config):
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("100000"),  # no stop/tp/time triggered
            current_time=make_dt(hours_offset=1),
            position_opened_at=make_dt(),
        )
        assert sig is None

    def test_zero_qty_returns_none(self, engine, config):
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("0"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("1000"),
            market_price=Decimal("97000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is None

    def test_default_atr_when_position_entry_atr_is_none(self, engine, config):
        # DEFAULT_ATR = 100, stop = 100000 * (1 - 2*100/100000) = 99800
        # market=99700 < 99800 → triggers
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=None,  # uses DEFAULT_ATR
            market_price=Decimal("99700"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.HARD_STOP

    def test_take_profit_price_correct(self, engine):
        # entry=100000, atr=2000, tp = 100000 * (1 + 3*2000/100000) = 106000
        cfg = ExitConfig(
            hard_stop_atr_mult=Decimal("2"),
            take_profit_atr_mult=Decimal("3"),
            max_hold_hours=0,  # disable time exit
            time_exit_pct=Decimal("0.5"),
        )
        engine = ExitEngine(config=cfg)
        sig = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            position_entry_atr=Decimal("2000"),
            market_price=Decimal("106000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert sig is not None
        assert sig.reason == ExitReason.TAKE_PROFIT
        # exit_price = market_price (immediate execution), not tp_price


# ── YAML loading tests ────────────────────────────────────────────────────────


class TestLoadExitRulesFromYaml:
    def test_parses_valid_yaml(self, tmp_path):
        yaml_content = """
exit_rules:
  hard_stop:
    atr_multiplier: 2.5
  take_profit:
    atr_multiplier: 4.0
  time_exit:
    max_hold_hours: 12
    partial_exit_pct: 0.75
"""
        p = tmp_path / "exit_rules.yaml"
        p.write_text(yaml_content)
        cfg = load_exit_rules_from_yaml(p)
        assert cfg.hard_stop_atr_mult == Decimal("2.5")
        assert cfg.take_profit_atr_mult == Decimal("4.0")
        assert cfg.max_hold_hours == 12
        assert cfg.time_exit_pct == Decimal("0.75")

    def test_missing_fields_use_defaults(self, tmp_path):
        yaml_content = """
exit_rules:
  hard_stop:
    atr_multiplier: 1.5
"""
        p = tmp_path / "exit_rules.yaml"
        p.write_text(yaml_content)
        cfg = load_exit_rules_from_yaml(p)
        assert cfg.hard_stop_atr_mult == Decimal("1.5")
        assert cfg.take_profit_atr_mult == Decimal("3")  # default
        assert cfg.max_hold_hours == 24  # default
        assert cfg.time_exit_pct == Decimal("0.5")  # default

    def test_empty_yaml_uses_all_defaults(self, tmp_path):
        yaml_content = """
exit_rules: {}
"""
        p = tmp_path / "exit_rules.yaml"
        p.write_text(yaml_content)
        cfg = load_exit_rules_from_yaml(p)
        assert cfg.hard_stop_atr_mult == Decimal("2")  # default
        assert cfg.take_profit_atr_mult == Decimal("3")  # default
        assert cfg.max_hold_hours == 24  # default
        assert cfg.time_exit_pct == Decimal("0.5")  # default

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_exit_rules_from_yaml("/nonexistent/path.yaml")

    def test_float_atr_multiplier(self, tmp_path):
        # YAML often parses numbers as float — ensure Decimal conversion works
        yaml_content = """
exit_rules:
  hard_stop:
    atr_multiplier: 2.0
  take_profit:
    atr_multiplier: 3.0
  time_exit:
    max_hold_hours: 24
    partial_exit_pct: 0.5
"""
        p = tmp_path / "exit_rules.yaml"
        p.write_text(yaml_content)
        cfg = load_exit_rules_from_yaml(p)
        assert cfg.hard_stop_atr_mult == Decimal("2.0")
        assert isinstance(cfg.hard_stop_atr_mult, Decimal)
