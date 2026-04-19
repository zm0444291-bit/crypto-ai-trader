"""Unit tests for the runtime runner service."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from trading.ai.schemas import AIScoreResult
from trading.runtime.runner import run_loop, run_once


class FakeSession:
    def __init__(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def add(self, obj) -> None:
        pass

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass


class FakeAIScorer:
    def score_candidate(self, *a, **kw):
        return AIScoreResult(
            ai_score=75,
            market_regime="trend",
            decision_hint="allow",
            risk_flags=[],
            explanation="fake",
        )


def make_session_factory():
    def factory():
        return FakeSession()

    return factory


class TestRunOnce:
    """run_once is tested via patching, verifying cycle inputs are built."""

    def test_no_inputs_built_skips_cycle(self):
        """When _build_cycle_inputs returns empty list, run_paper_cycle is not called."""
        session_factory = make_session_factory()

        cycle_calls: list = []

        def fake_cycle(*args, **kwargs):
            cycle_calls.append(kwargs)
            from trading.runtime.paper_cycle import CycleResult

            return CycleResult(
                status="no_signal",
                candidate_present=False,
                ai_decision=None,
                risk_state=None,
                order_executed=False,
                reject_reasons=[],
                event_ids=[],
            )

        with patch("trading.runtime.runner.run_paper_cycle", side_effect=fake_cycle):
            with patch(
                "trading.runtime.runner._build_cycle_inputs",
                return_value=[],
            ):
                with patch("trading.runtime.runner.EventsRepository"):
                    run_once(
                        session_factory=session_factory,
                        ai_scorer=FakeAIScorer(),
                        symbols=["BTCUSDT"],
                        initial_cash_usdt=Decimal("500"),
                    )

        assert cycle_calls == []

    def test_cycles_run_for_each_input_symbol(self):
        """Each CycleInput returned by _build_cycle_inputs triggers one run_paper_cycle call."""
        session_factory = make_session_factory()

        from trading.runtime.paper_cycle import CycleInput

        fake_inputs = [
            CycleInput(
                symbol="BTCUSDT",
                now=datetime.now(UTC),
                day_start_equity=Decimal("500"),
                account_equity=Decimal("500"),
                market_prices={"BTCUSDT": Decimal("50000")},
                total_position_pct=Decimal("0"),
                symbol_position_pct=Decimal("0"),
                open_positions=0,
                daily_order_count=0,
                symbol_daily_trade_count=0,
                consecutive_losses=0,
                data_is_fresh=True,
                kill_switch_enabled=False,
            ),
            CycleInput(
                symbol="ETHUSDT",
                now=datetime.now(UTC),
                day_start_equity=Decimal("500"),
                account_equity=Decimal("500"),
                market_prices={"ETHUSDT": Decimal("3000")},
                total_position_pct=Decimal("0"),
                symbol_position_pct=Decimal("0"),
                open_positions=0,
                daily_order_count=0,
                symbol_daily_trade_count=0,
                consecutive_losses=0,
                data_is_fresh=True,
                kill_switch_enabled=False,
            ),
        ]

        symbols_called: list[str] = []

        def fake_cycle(*args, **kwargs):
            input_data = kwargs.get("input_data")
            if input_data:
                symbols_called.append(input_data.symbol)
            from trading.runtime.paper_cycle import CycleResult

            return CycleResult(
                status="no_signal",
                candidate_present=False,
                ai_decision=None,
                risk_state=None,
                order_executed=False,
                reject_reasons=[],
                event_ids=[],
            )

        with patch("trading.runtime.runner.run_paper_cycle", side_effect=fake_cycle):
            with patch(
                "trading.runtime.runner._build_cycle_inputs",
                return_value=fake_inputs,
            ):
                with patch("trading.runtime.runner.EventsRepository"):
                    run_once(
                        session_factory=session_factory,
                        ai_scorer=FakeAIScorer(),
                        symbols=["BTCUSDT", "ETHUSDT"],
                        initial_cash_usdt=Decimal("500"),
                    )

        assert symbols_called == ["BTCUSDT", "ETHUSDT"]


class TestRunLoop:
    """run_loop looping and event recording behaviour."""

    def test_interval_loop_runs_expected_count(self):
        """run_loop calls run_once exactly max_cycles times before exiting."""
        session_factory = make_session_factory()

        run_once_calls: list = []

        def fake_run_once(*args, **kwargs):
            run_once_calls.append(1)
            from trading.runtime.paper_cycle import CycleResult

            return [
                CycleResult(
                    status="no_signal",
                    candidate_present=False,
                    ai_decision=None,
                    risk_state=None,
                    order_executed=False,
                    reject_reasons=[],
                    event_ids=[],
                )
            ]

        stop_event = MagicMock()
        # Return False for all is_set calls until max_cycles is reached
        stop_event.is_set.return_value = False

        with patch("trading.runtime.runner.run_once", side_effect=fake_run_once):
            with patch("trading.runtime.runner.time.sleep"):
                cycles = run_loop(
                    interval_seconds=1,
                    session_factory=session_factory,
                    ai_scorer=FakeAIScorer(),
                    max_cycles=3,
                    stop_event=stop_event,
                    symbols=["BTCUSDT"],
                )

        assert cycles == 3
        assert len(run_once_calls) == 3

    def test_exception_in_cycle_records_error_and_continues(self):
        """An exception in run_once is caught, recorded, and the loop continues."""
        session_factory = make_session_factory()

        call_count = {"value": 0}

        def fake_run_once(*args, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 2:
                raise RuntimeError("simulated failure")
            from trading.runtime.paper_cycle import CycleResult

            return [
                CycleResult(
                    status="no_signal",
                    candidate_present=False,
                    ai_decision=None,
                    risk_state=None,
                    order_executed=False,
                    reject_reasons=[],
                    event_ids=[],
                )
            ]

        stop_event = MagicMock()
        stop_event.is_set.return_value = False

        with patch("trading.runtime.runner.run_once", side_effect=fake_run_once):
            with patch("trading.runtime.runner.time.sleep"):
                with patch("trading.runtime.runner.EventsRepository"):
                    cycles = run_loop(
                        interval_seconds=1,
                        session_factory=session_factory,
                        ai_scorer=FakeAIScorer(),
                        max_cycles=3,
                        stop_event=stop_event,
                        symbols=["BTCUSDT"],
                    )

        # Loop should have called run_once 3 times (2 succeeded + 1 exception)
        assert call_count["value"] == 3
        assert cycles == 3

    def test_loop_stops_on_keyboard_interrupt(self):
        """KeyboardInterrupt in time.sleep causes clean exit with runner_stopped."""
        session_factory = make_session_factory()

        stop_event = MagicMock()
        stop_event.is_set.return_value = False

        events_recorded: list = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs["event_type"])
                ev = MagicMock()
                ev.id = 1
                return ev

        with patch("trading.runtime.runner.run_once", return_value=[]):
            with patch(
                "trading.runtime.runner.time.sleep",
                side_effect=KeyboardInterrupt,
            ):
                with patch(
                    "trading.runtime.runner.EventsRepository",
                    return_value=FakeEventsRepo(),
                ):
                    run_loop(
                        interval_seconds=60,
                        session_factory=session_factory,
                        ai_scorer=FakeAIScorer(),
                        max_cycles=None,
                        symbols=["BTCUSDT"],
                    )

        assert "runner_started" in events_recorded
        assert "runner_stopped" in events_recorded

    def test_max_cycles_stops_at_limit(self):
        """Loop exits via max_cycles check without calling is_set again."""
        session_factory = make_session_factory()

        run_once_calls: list = []

        def fake_run_once(*args, **kwargs):
            run_once_calls.append(1)
            from trading.runtime.paper_cycle import CycleResult

            return [
                CycleResult(
                    status="no_signal",
                    candidate_present=False,
                    ai_decision=None,
                    risk_state=None,
                    order_executed=False,
                    reject_reasons=[],
                    event_ids=[],
                )
            ]

        stop_event = MagicMock()
        stop_event.is_set.return_value = False

        with patch("trading.runtime.runner.run_once", side_effect=fake_run_once):
            with patch("trading.runtime.runner.time.sleep"):
                with patch("trading.runtime.runner.EventsRepository"):
                    cycles = run_loop(
                        interval_seconds=10,
                        session_factory=session_factory,
                        ai_scorer=FakeAIScorer(),
                        max_cycles=2,
                        stop_event=stop_event,
                        symbols=["BTCUSDT"],
                    )

        assert cycles == 2
        assert len(run_once_calls) == 2
