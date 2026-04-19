"""Unit tests for the supervisor module and supervisor CLI mode."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from trading.ai.schemas import AIScoreResult
from trading.runtime.supervisor import (
    INGESTION_DEFAULT_INTERVAL,
    TRADING_DEFAULT_INTERVAL,
    run_supervisor,
)


class FakeSession:
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


class TestRunSupervisor:
    """run_supervisor starts both loops and shuts down cleanly."""

    def test_starts_both_loops_with_expected_arguments(self):
        """Both ingest_loop and run_loop are called with the correct arguments."""
        ingest_calls: list = []
        trade_calls: list = []

        def fake_ingest_loop(**kwargs):
            ingest_calls.append(kwargs)
            # Simulate one cycle then stop by setting the stop event
            kwargs["stop_event"].set()

        def fake_run_loop(**kwargs):
            trade_calls.append(kwargs)
            kwargs["stop_event"].set()

        with patch("trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                run_supervisor(
                    session_factory=make_session_factory(),
                    ai_scorer=FakeAIScorer(),
                    ingest_interval=120,
                    trade_interval=60,
                    max_cycles=5,
                    symbols=["BTCUSDT", "ETHUSDT"],
                    initial_cash_usdt=Decimal("1000"),
                )

        assert len(ingest_calls) == 1
        assert ingest_calls[0]["interval_seconds"] == 120
        assert ingest_calls[0]["max_cycles"] == 5
        assert ingest_calls[0]["symbols"] == ["BTCUSDT", "ETHUSDT"]

        assert len(trade_calls) == 1
        assert trade_calls[0]["interval_seconds"] == 60
        assert trade_calls[0]["max_cycles"] == 5
        assert trade_calls[0]["symbols"] == ["BTCUSDT", "ETHUSDT"]
        assert trade_calls[0]["initial_cash_usdt"] == Decimal("1000")

    def test_shutdown_sets_stop_and_joins_threads(self):
        """KeyboardInterrupt sets stop and both threads are joined."""
        ingest_calls = []
        trade_calls = []

        def fake_ingest_loop(**kwargs):
            ingest_calls.append(kwargs)
            # Simulate loop running then stopping via stop_event
            kwargs["stop_event"].wait(timeout=0.5)  # wait for stop signal

        def fake_run_loop(**kwargs):
            trade_calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=0.5)

        with patch("trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                run_supervisor(
                    session_factory=make_session_factory(),
                    ai_scorer=FakeAIScorer(),
                    ingest_interval=300,
                    trade_interval=300,
                )

        # Both loops ran and received the shared stop event
        assert len(ingest_calls) == 1
        assert len(trade_calls) == 1
        # The stop event was shared between both loops
        assert ingest_calls[0]["stop_event"] is trade_calls[0]["stop_event"]

    def test_component_exception_records_error_and_raises(self):
        """When one loop raises unexpectedly, supervisor_component_error is recorded."""
        errors_recorded = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                errors_recorded.append(kwargs)

        def fake_ingest_loop(**kwargs):
            # Wait for stop signal before exiting. The main loop will keep
            # polling until ingest_thread.is_alive()==False, which only happens
            # after ingest_loop returns — giving _record_component_error time
            # to run in the trading thread before supervisor_exit.
            kwargs["stop_event"].wait(timeout=5)

        def fake_run_loop(**kwargs):
            raise RuntimeError("trading loop crashed")

        with patch(
            "trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop
        ):
            with patch(
                "trading.runtime.supervisor.run_loop", side_effect=fake_run_loop
            ):
                with patch(
                    "trading.runtime.supervisor.EventsRepository",
                    return_value=FakeEventsRepo(),
                ):
                    with pytest.raises(RuntimeError, match="trading loop crashed"):
                        run_supervisor(
                            session_factory=make_session_factory(),
                            ai_scorer=FakeAIScorer(),
                            ingest_interval=300,
                            trade_interval=300,
                        )

        # Error event was recorded
        assert any(
            e["event_type"] == "supervisor_component_error"
            and e["context"]["component"] == "trading"
            for e in errors_recorded
        )

    def test_raises_error_when_both_loops_fail(self):
        """When both loops raise, a combined RuntimeError is raised."""

        def fake_ingest_loop(**kwargs):
            raise RuntimeError("ingestion failed")

        def fake_run_loop(**kwargs):
            raise RuntimeError("trading failed")

        with patch("trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                with pytest.raises(RuntimeError, match="Both loops failed"):
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                    )

    def test_default_intervals_are_constants(self):
        """Default intervals match the CLI defaults."""
        assert INGESTION_DEFAULT_INTERVAL == 300
        assert TRADING_DEFAULT_INTERVAL == 300

    def test_invalid_ingest_interval_raises(self):
        """ingest_interval < 1 raises ValueError before threads start."""
        with pytest.raises(ValueError, match="ingest_interval must be >= 1"):
            run_supervisor(
                session_factory=make_session_factory(),
                ai_scorer=FakeAIScorer(),
                ingest_interval=0,
                trade_interval=300,
            )

    def test_invalid_trade_interval_raises(self):
        """trade_interval < 1 raises ValueError before threads start."""
        with pytest.raises(ValueError, match="trade_interval must be >= 1"):
            run_supervisor(
                session_factory=make_session_factory(),
                ai_scorer=FakeAIScorer(),
                ingest_interval=300,
                trade_interval=0,
            )

    def test_blocks_until_threads_exit_naturally_with_max_cycles(self):
        """With bounded max_cycles, supervisor blocks until both loops finish, then returns."""
        call_order: list[str] = []

        def fake_ingest_loop(**kwargs):
            call_order.append("ingest_start")
            kwargs["stop_event"].set()  # stop immediately — one cycle
            call_order.append("ingest_stopped")

        def fake_run_loop(**kwargs):
            call_order.append("trade_start")
            kwargs["stop_event"].set()  # stop immediately — one cycle
            call_order.append("trade_stopped")

        with patch(
            "trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop
        ):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                run_supervisor(
                    session_factory=make_session_factory(),
                    ai_scorer=FakeAIScorer(),
                    ingest_interval=300,
                    trade_interval=300,
                    max_cycles=1,
                )

        # Both loops must have fully started and stopped
        assert "ingest_start" in call_order
        assert "ingest_stopped" in call_order
        assert "trade_start" in call_order
        assert "trade_stopped" in call_order
        # Supervisor must NOT have recorded stopped until both threads were done
        # (if it had falsely returned early, we'd only see partial call_order)

    def test_stop_recorded_only_after_threads_dead(self):
        """supervisor_stopped is never recorded while any thread is still alive."""
        events_recorded: list[str] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs["event_type"])

        def fake_ingest_loop(**kwargs):
            kwargs["stop_event"].set()

        def fake_run_loop(**kwargs):
            kwargs["stop_event"].set()

        with patch(
            "trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop
        ):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                with patch(
                    "trading.runtime.supervisor.EventsRepository",
                    return_value=FakeEventsRepo(),
                ):
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                        max_cycles=1,
                    )

        # supervisor_stopped must appear in events, and it must be the last event
        assert "supervisor_stopped" in events_recorded
        assert events_recorded[-1] == "supervisor_stopped"

    def test_component_exception_sets_stop_and_waits_for_other_thread(self):
        """When one loop crashes, stop is set and we wait for the other thread to finish."""
        call_order: list[str] = []

        def fake_ingest_loop(**kwargs):
            call_order.append("ingest_start")
            kwargs["stop_event"].wait(timeout=2)  # wait for stop signal
            call_order.append("ingest_stopped")

        def fake_run_loop(**kwargs):
            call_order.append("trade_start")
            raise RuntimeError("trading crashed")

        with patch(
            "trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop
        ):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                with pytest.raises(RuntimeError, match="trading crashed"):
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                    )

        # Trading must have started and crashed
        assert "trade_start" in call_order
        # Ingestion must have also started and received stop signal (so it could stop)
        assert "ingest_start" in call_order
        # Supervisor must have waited for ingestion to stop before re-raising
        assert "ingest_stopped" in call_order


class TestSupervisorCLI:
    """CLI correctly parses --supervisor and related flags."""

    def test_supervisor_mode_parses_ingest_and_trade_intervals(self):
        """--supervisor --ingest-interval and --trade-interval parse without error."""
        import sys

        from trading.runtime.cli import main

        fake_run_supervisor = MagicMock()
        fake_session_factory = MagicMock()
        fake_ai_scorer = MagicMock()

        sf_patch = patch(
            "trading.runtime.cli.create_runner_session_factory",
            return_value=fake_session_factory,
        )
        scorer_patch = patch(
            "trading.runtime.cli.AIScorer",
            return_value=fake_ai_scorer,
        )
        super_patch = patch(
            "trading.runtime.cli.run_supervisor",
            fake_run_supervisor,
        )
        argv_patch = patch.object(
            sys,
            "argv",
            ["cli", "--supervisor", "--ingest-interval", "120", "--trade-interval", "60"],
        )
        with sf_patch, scorer_patch, super_patch, argv_patch:
            main()

        fake_run_supervisor.assert_called_once()
        call_kwargs = fake_run_supervisor.call_args.kwargs
        assert call_kwargs["ingest_interval"] == 120
        assert call_kwargs["trade_interval"] == 60

    def test_supervisor_mode_includes_max_cycles(self):
        """--supervisor --max-cycles is passed through to run_supervisor."""
        import sys

        from trading.runtime.cli import main

        fake_run_supervisor = MagicMock()
        fake_session_factory = MagicMock()
        fake_ai_scorer = MagicMock()

        sf_patch = patch(
            "trading.runtime.cli.create_runner_session_factory",
            return_value=fake_session_factory,
        )
        scorer_patch = patch(
            "trading.runtime.cli.AIScorer",
            return_value=fake_ai_scorer,
        )
        super_patch = patch(
            "trading.runtime.cli.run_supervisor",
            fake_run_supervisor,
        )
        argv_patch = patch.object(
            sys, "argv", ["cli", "--supervisor", "--max-cycles", "10"]
        )
        with sf_patch, scorer_patch, super_patch, argv_patch:
            main()

        assert fake_run_supervisor.call_args.kwargs["max_cycles"] == 10

    def test_existing_once_mode_still_works(self):
        """--once flag still runs run_once (no regression)."""
        import sys

        from trading.runtime.cli import main

        fake_run_once = MagicMock(return_value=[])
        fake_session_factory = MagicMock()
        fake_ai_scorer = MagicMock()

        sf_patch = patch(
            "trading.runtime.cli.create_runner_session_factory",
            return_value=fake_session_factory,
        )
        scorer_patch = patch(
            "trading.runtime.cli.AIScorer",
            return_value=fake_ai_scorer,
        )
        once_patch = patch("trading.runtime.cli.run_once", fake_run_once)
        argv_patch = patch.object(sys, "argv", ["cli", "--once"])
        with sf_patch, scorer_patch, once_patch, argv_patch:
            main()

        fake_run_once.assert_called_once()

    def test_existing_interval_mode_still_works(self):
        """--interval flag still runs run_loop (no regression)."""
        import sys

        from trading.runtime.cli import main

        fake_run_loop = MagicMock(return_value=5)
        fake_session_factory = MagicMock()
        fake_ai_scorer = MagicMock()

        sf_patch = patch(
            "trading.runtime.cli.create_runner_session_factory",
            return_value=fake_session_factory,
        )
        scorer_patch = patch(
            "trading.runtime.cli.AIScorer",
            return_value=fake_ai_scorer,
        )
        loop_patch = patch("trading.runtime.cli.run_loop", fake_run_loop)
        argv_patch = patch.object(
            sys, "argv", ["cli", "--interval", "60", "--max-cycles", "3"]
        )
        with sf_patch, scorer_patch, loop_patch, argv_patch:
            main()

        fake_run_loop.assert_called_once()
        assert fake_run_loop.call_args.kwargs["interval_seconds"] == 60
        assert fake_run_loop.call_args.kwargs["max_cycles"] == 3
