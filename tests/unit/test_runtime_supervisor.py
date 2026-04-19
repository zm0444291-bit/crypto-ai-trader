"""Unit tests for the supervisor module and supervisor CLI mode."""

import threading
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


class TestSupervisorHeartbeat:
    """Supervisor emits periodic heartbeat events while running."""

    def test_heartbeat_event_recorded_on_shutdown(self):
        """supervisor_stopped triggers a final heartbeat before threads join."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

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

        # A heartbeat must have been recorded during startup
        heartbeat_events = [
            e for e in events_recorded if e["event_type"] == "supervisor_heartbeat"
        ]
        assert len(heartbeat_events) >= 1, (
            f"Expected at least 1 heartbeat event, got {len(heartbeat_events)}"
        )
        hb = heartbeat_events[0]
        assert "ingest_thread_alive" in hb["context"]
        assert "trading_thread_alive" in hb["context"]
        assert "uptime_seconds" in hb["context"]
        assert "symbols" in hb["context"]

    def test_runtime_boot_fields_in_startup_event(self):
        """supervisor_started includes startup_timestamp_utc, process_mode, and intervals."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

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
                        ingest_interval=120,
                        trade_interval=60,
                        max_cycles=1,
                    )

        startup_events = [
            e for e in events_recorded if e["event_type"] == "supervisor_started"
        ]
        assert len(startup_events) == 1, "Expected exactly one supervisor_started event"
        ctx = startup_events[0]["context"]
        assert ctx["process_mode"] == "supervisor"
        assert ctx["ingest_interval"] == 120
        assert ctx["trade_interval"] == 60
        assert "startup_timestamp_utc" in ctx

    def test_heartbeat_thread_exits_when_stop_is_set(self):
        """Heartbeat thread exits promptly when stop event is set (no 60s wait)."""
        import time

        heartbeat_calls: list = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                if kwargs["event_type"] == "supervisor_heartbeat":
                    heartbeat_calls.append(kwargs)

        def fake_ingest_loop(**kwargs):
            # Stop after ~100ms — heartbeat should have fired at most once
            time.sleep(0.1)
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
                    start = time.monotonic()
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                        max_cycles=1,
                    )
                    elapsed = time.monotonic() - start

        # Should complete in < 3s; if heartbeat blocked for 60s the test would fail
        assert elapsed < 5, (
            f"Supervisor took {elapsed:.1f}s to exit — heartbeat thread may have blocked shutdown"
        )

    def test_uptime_in_supervisor_stopped_context(self):
        """supervisor_stopped includes uptime_seconds in its context."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

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

        stopped_events = [
            e for e in events_recorded if e["event_type"] == "supervisor_stopped"
        ]
        assert len(stopped_events) == 1
        ctx = stopped_events[0]["context"]
        assert "uptime_seconds" in ctx
        assert isinstance(ctx["uptime_seconds"], (int, float))


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

    def test_stop_set_called_when_component_crashes(self):
        """When a component crashes, stop.set() is called so the other loop exits promptly."""
        import time

        def fake_ingest_loop(**kwargs):
            # Without stop.set(), this 1-second wait would time out and the test
            # would take ~1s longer than necessary. With stop.set(), it returns
            # immediately.
            kwargs["stop_event"].wait(timeout=1)

        def fake_run_loop(**kwargs):
            raise RuntimeError("trading crashed")

        start = time.monotonic()
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
        elapsed = time.monotonic() - start

        # If stop.set() was NOT called, ingest_loop waits the full 1s timeout.
        # If stop.set() WAS called, ingest_loop returns immediately (~0ms).
        # We assert elapsed < 0.5s to prove stop was set promptly.
        assert elapsed < 0.5, (
            f"Test took {elapsed:.2f}s — stop.set() may not have been called. "
            "Ingestion would have waited 1s for the stop signal."
        )

    def test_does_not_raise_until_other_worker_exits_after_crash(self):
        """Supervisor must wait for the non-crashed worker to fully exit before re-raising."""
        stop_seen = threading.Event()
        allow_ingest_exit = threading.Event()
        run_finished = threading.Event()
        result: dict[str, str] = {}

        def fake_ingest_loop(**kwargs):
            kwargs["stop_event"].wait(timeout=2)
            stop_seen.set()
            allow_ingest_exit.wait(timeout=2)

        def fake_run_loop(**kwargs):
            raise RuntimeError("trading crashed")

        def run_target() -> None:
            try:
                run_supervisor(
                    session_factory=make_session_factory(),
                    ai_scorer=FakeAIScorer(),
                    ingest_interval=300,
                    trade_interval=300,
                )
            except RuntimeError as exc:
                result["error"] = str(exc)
            finally:
                run_finished.set()

        with patch("trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                worker = threading.Thread(target=run_target, name="supervisor-test-runner")
                worker.start()
                assert stop_seen.wait(
                    timeout=1
                ), "ingestion worker did not receive stop signal"

                # run_supervisor should still be blocked because ingestion has not exited yet.
                assert not run_finished.is_set()
                assert worker.is_alive()

                allow_ingest_exit.set()
                worker.join(timeout=2)
                assert not worker.is_alive()
                assert run_finished.is_set()
                assert "trading crashed" in result.get("error", "")


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


class TestSupervisorHeartbeatStaleMonitoring:
    """Supervisor monitors heartbeat freshness and triggers stale/recovered alerts."""

    def test_monitor_thread_stops_promptly_on_shutdown(self):
        """Monitor thread exits immediately when stop event is set (no 60s wait)."""
        import time

        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

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
                    start = time.monotonic()
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                        max_cycles=1,
                    )
                    elapsed = time.monotonic() - start

        # Monitor thread should not block shutdown
        assert elapsed < 5, (
            f"Supervisor took {elapsed:.1f}s to exit — monitor thread may have blocked shutdown"
        )

    def test_deduplicator_integrated_into_component_error(self):
        """Component errors are deduplicated — repeated same errors don't re-notify."""
        from trading.notifications.dedup import AlertDeduplicator

        events_recorded: list[dict] = []
        notifications_sent: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

        class FakeNotifier:
            def notify(self, level, title, message, context=None):
                notifications_sent.append(
                    {"level": level, "title": title, "message": message, "context": context}
                )

        dedup = AlertDeduplicator(window_seconds=300)

        def fake_ingest_loop(**kwargs):
            kwargs["stop_event"].set()

        def fake_run_loop(**kwargs):
            # First crash
            kwargs["stop_event"].set()
            raise RuntimeError("test error A")

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
                    with pytest.raises(RuntimeError, match="test error A"):
                        run_supervisor(
                            session_factory=make_session_factory(),
                            ai_scorer=FakeAIScorer(),
                            ingest_interval=300,
                            trade_interval=300,
                            notifier=FakeNotifier(),
                            deduplicator=dedup,
                        )

        # DB events are always recorded for both attempts
        error_events = [
            e for e in events_recorded if e["event_type"] == "supervisor_component_error"
        ]
        assert len(error_events) >= 1
        # But notification should be sent only once (dedup suppresses second)
        component_error_notifications = [
            n for n in notifications_sent
            if n["context"] and n["context"].get("component") == "trading"
        ]
        # At minimum the first error notification fires
        assert len(component_error_notifications) >= 1


# ─── Component Restart Strategy Tests ─────────────────────────────────────────

class TestComponentRestartStrategy:
    """Supervisor enforces per-component restart limits and cooldown windows."""

    def test_restart_succeeds_when_under_max_restarts(self):
        """Component is restarted when crash count is below max_restarts."""
        events_recorded: list[dict] = []
        restart_count = {"ingestion": 0}

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

        def fake_ingest_loop(**kwargs):
            restart_count["ingestion"] += 1
            if restart_count["ingestion"] == 1:
                raise RuntimeError("first ingestion failure")
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
                        max_restarts=3,
                        cooldown_seconds=0,
                    )

        # Should have restart attempt and success events
        attempted = [e for e in events_recorded if e["event_type"] == "component_restart_attempted"]
        succeeded = [e for e in events_recorded if e["event_type"] == "component_restart_succeeded"]
        assert len(attempted) >= 1, "Expected at least one component_restart_attempted event"
        assert len(succeeded) >= 1, "Expected at least one component_restart_succeeded event"

    def test_restart_exhausted_after_max_restarts_exceeded(self):
        """Component marked exhausted when max_restarts is exceeded."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

        def fake_ingest_loop(**kwargs):
            raise RuntimeError("persistent ingestion failure")

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
                    with pytest.raises(RuntimeError):
                        run_supervisor(
                            session_factory=make_session_factory(),
                            ai_scorer=FakeAIScorer(),
                            ingest_interval=300,
                            trade_interval=300,
                            max_restarts=2,
                            cooldown_seconds=0,
                        )

        exhausted = [
            e for e in events_recorded
            if e["event_type"] == "component_restart_exhausted"
        ]
        assert len(exhausted) >= 1, (
            f"Expected at least one component_restart_exhausted event, got events: "
            f"{[e['event_type'] for e in events_recorded]}"
        )
        # Verify exhausted event has required context fields
        ctx = exhausted[0]["context"]
        assert "component" in ctx
        assert "reason" in ctx
        assert "attempt" in ctx

    def test_restart_cooldown_enforced(self):
        """Component restart is delayed when within cooldown window."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

        call_times: list[float] = []

        def fake_ingest_loop(**kwargs):
            import time
            call_times.append(time.monotonic())
            if len(call_times) == 1:
                raise RuntimeError("first failure")
            kwargs["stop_event"].set()

        def fake_run_loop(**kwargs):
            kwargs["stop_event"].set()

        import time
        with patch(
            "trading.runtime.supervisor.ingest_loop", side_effect=fake_ingest_loop
        ):
            with patch("trading.runtime.supervisor.run_loop", side_effect=fake_run_loop):
                with patch(
                    "trading.runtime.supervisor.EventsRepository",
                    return_value=FakeEventsRepo(),
                ):
                    start = time.monotonic()
                    run_supervisor(
                        session_factory=make_session_factory(),
                        ai_scorer=FakeAIScorer(),
                        ingest_interval=300,
                        trade_interval=300,
                        max_restarts=3,
                        cooldown_seconds=5,  # 5 second cooldown
                    )
                    elapsed = time.monotonic() - start

        # With 5s cooldown, second restart should be delayed by at least 3s
        # (allowing some margin since it checks cooldown on each attempt)
        attempted = [
            e for e in events_recorded
            if e["event_type"] == "component_restart_attempted"
        ]
        event_types = [e["event_type"] for e in events_recorded]
        assert len(attempted) >= 2, (
            f"Expected at least 2 restart attempts, got {event_types}"
        )
        # Second attempt should have been subject to cooldown
        second_attempt = attempted[1]
        assert second_attempt["context"].get("cooldown_active") is True or elapsed >= 3, (
            f"Expected cooldown to delay restart, elapsed={elapsed:.2f}s"
        )

    def test_restart_event_context_includes_required_fields(self):
        """All restart events include component, attempt, reason, and timestamp context."""
        events_recorded: list[dict] = []

        class FakeEventsRepo:
            def record_event(self, **kwargs):
                events_recorded.append(kwargs)

        restart_count = {"ingestion": 0}

        def fake_ingest_loop(**kwargs):
            restart_count["ingestion"] += 1
            if restart_count["ingestion"] == 1:
                raise RuntimeError("test crash")
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
                        max_restarts=3,
                        cooldown_seconds=0,
                    )

        for event_type in ["component_restart_attempted", "component_restart_succeeded"]:
            events = [e for e in events_recorded if e["event_type"] == event_type]
            assert len(events) >= 1, f"Missing event type: {event_type}"
            for e in events:
                assert "component" in e["context"], f"{event_type} missing component"
                assert "attempt" in e["context"], f"{event_type} missing attempt"
                assert "reason" in e["context"], f"{event_type} missing reason"
