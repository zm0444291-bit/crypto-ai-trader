"""Unit tests for the exit engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading.strategies.exits import (
    ExitEngine,
    ExitReason,
    ExitSignal,
    HardStopRule,
    TakeProfitRule,
    TimeExitRule,
)


def make_dt(hours_offset: int = 0) -> datetime:
    return datetime(2026, 4, 20, 12, 0, tzinfo=UTC) + timedelta(hours=hours_offset)


class TestHardStopRule:
    def test_triggers_when_market_at_or_below_stop(self):
        rule = HardStopRule(stop_reference=Decimal("95000"))

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("95000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.HARD_STOP
        assert signal.exit_price == Decimal("95000")
        assert signal.qty_to_exit == Decimal("1")

    def test_does_not_trigger_above_stop(self):
        rule = HardStopRule(stop_reference=Decimal("95000"))

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("96000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is None

    def test_triggers_on_breach_below_stop(self):
        rule = HardStopRule(stop_reference=Decimal("95000"))

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("2"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("94000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.qty_to_exit == Decimal("2")


class TestTakeProfitRule:
    def test_triggers_when_market_at_or_above_target(self):
        rule = TakeProfitRule(target_price=Decimal("105000"))

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("105000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.TAKE_PROFIT
        assert signal.exit_price == Decimal("105000")

    def test_does_not_trigger_below_target(self):
        rule = TakeProfitRule(target_price=Decimal("105000"))

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("104000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is None


class TestTimeExitRule:
    def test_triggers_after_max_hours(self):
        rule = TimeExitRule(max_hours=24)

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=25),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.TIME_EXIT
        assert signal.qty_to_exit == Decimal("1")

    def test_does_not_trigger_before_max_hours(self):
        rule = TimeExitRule(max_hours=24)

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=12),
            position_opened_at=make_dt(),
        )

        assert signal is None

    def test_uses_position_opened_at_for_elapsed_time(self):
        rule = TimeExitRule(max_hours=24)

        signal = rule.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            market_price=Decimal("100000"),
            current_time=make_dt(hours_offset=10),
            position_opened_at=make_dt(hours_offset=-14),  # opened 14h before now = 24h ago
        )

        # Exactly 24h elapsed >= max_hours → triggers (>= not >)
        assert signal is not None
        assert signal.reason == ExitReason.TIME_EXIT


class TestExitEngine:
    def test_returns_first_triggered_signal(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("95000"),
            take_profit_pct=Decimal("5"),
            max_hours=24,
        )

        # Hard stop should trigger before take profit
        signal = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            market_price=Decimal("94000"),  # below stop AND below TP target
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.HARD_STOP

    def test_returns_take_profit_when_stop_not_breached(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("95000"),
            take_profit_pct=Decimal("5"),  # target = 105000
            max_hours=24,
        )

        signal = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            market_price=Decimal("106000"),  # above TP target
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.TAKE_PROFIT
        # tp_target = 100000 * (1 + 5/100) = 105000
        assert signal.exit_price == Decimal("105000")

    def test_uses_position_stop_over_engine_default(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("99000"),  # higher than position stop
            take_profit_pct=Decimal("0"),
            max_hours=0,
        )

        # position_stop is lower, so not triggered at 98500
        signal_none = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=Decimal("98000"),  # lower than engine default
            market_price=Decimal("98500"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert signal_none is None  # 98500 > 98000 stop

        # position_stop is breached
        signal_hit = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=Decimal("98500"),
            market_price=Decimal("98500"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )
        assert signal_hit is not None
        assert signal_hit.reason == ExitReason.HARD_STOP
        assert signal_hit.exit_price == Decimal("98500")

    def test_time_exit_triggers_when_held_long_enough(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("95000"),
            take_profit_pct=Decimal("5"),
            max_hours=4,
        )

        signal = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            market_price=Decimal("100000"),  # no stop/tp triggered
            current_time=make_dt(hours_offset=5),
            position_opened_at=make_dt(),
        )

        assert signal is not None
        assert signal.reason == ExitReason.TIME_EXIT

    def test_returns_none_when_no_rule_triggers(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("95000"),
            take_profit_pct=Decimal("5"),
            max_hours=24,
        )

        signal = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("1"),
            position_avg_entry=Decimal("100000"),
            position_stop=None,
            market_price=Decimal("100000"),  # not below stop, not at TP, not timed out
            current_time=make_dt(hours_offset=1),
            position_opened_at=make_dt(),
        )

        assert signal is None

    def test_partial_exit_when_signal_specifies_smaller_qty(self):
        # Constructing a partial exit signal directly (ExitEngine not needed here)
        partial_signal = ExitSignal(
            symbol="BTCUSDT",
            reason=ExitReason.HARD_STOP,
            exit_price=Decimal("95000"),
            qty_to_exit=Decimal("0.5"),  # half the position
            created_at=make_dt(),
            confidence=Decimal("1.0"),
        )

        assert partial_signal.qty_to_exit == Decimal("0.5")
        assert partial_signal.reason == ExitReason.HARD_STOP

        assert partial_signal.qty_to_exit == Decimal("0.5")

    def test_exit_engine_evaluate_returns_none_when_no_position(self):
        engine = ExitEngine(
            hard_stop_reference=Decimal("95000"),
            take_profit_pct=Decimal("5"),
            max_hours=24,
        )

        signal = engine.evaluate(
            symbol="BTCUSDT",
            position_qty=Decimal("0"),  # no position
            position_avg_entry=Decimal("0"),
            position_stop=None,
            market_price=Decimal("100000"),
            current_time=make_dt(),
            position_opened_at=make_dt(),
        )

        # All rules need a qty > 0 to produce a signal
        assert signal is None
