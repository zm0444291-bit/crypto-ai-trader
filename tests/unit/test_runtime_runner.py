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
                symbol="BTCUSDT",
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
                symbol="BTCUSDT",
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
                    symbol="BTCUSDT",
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
                    symbol="BTCUSDT",
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
                    symbol="BTCUSDT",
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


class TestDayBaseline:
    """Regression tests for daily equity baseline persistence."""

    def test_same_day_baseline_reuse(self):
        """Second call on the same UTC day returns the stored baseline, not current equity."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _get_or_create_day_baseline

        now = datetime.now(UTC)
        today_str = str(now.date())

        stored_event = MagicMock()
        stored_event.event_type = "day_baseline_set"
        stored_event.context_json = {"date": today_str, "baseline": "500.00"}

        fake_events_repo = MagicMock()
        fake_events_repo.get_latest_event_by_type.return_value = stored_event

        fake_session = MagicMock()

        with patch(
            "trading.runtime.runner.EventsRepository",
            return_value=fake_events_repo,
        ):
            result1 = _get_or_create_day_baseline(fake_session, now, Decimal("500"))
            result2 = _get_or_create_day_baseline(fake_session, now, Decimal("480"))

        # Same UTC day → baseline from stored event, not current equity
        assert result1 == result2 == Decimal("500.00")
        # No new event should have been recorded (existing baseline was found)
        assert fake_events_repo.record_event.call_count == 0

    def test_next_day_baseline_rotates(self):
        """When the most recent baseline is from a prior UTC day, a new one is created."""
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _get_or_create_day_baseline

        now = datetime.now(UTC)
        today_str = str(now.date())
        yesterday = str((now - timedelta(days=1)).date())

        old_event = MagicMock()
        old_event.event_type = "day_baseline_set"
        old_event.context_json = {"date": yesterday, "baseline": "400.00"}

        fake_events_repo = MagicMock()
        fake_events_repo.get_latest_event_by_type.return_value = old_event

        fake_session = MagicMock()

        with patch(
            "trading.runtime.runner.EventsRepository",
            return_value=fake_events_repo,
        ):
            baseline = _get_or_create_day_baseline(fake_session, now, Decimal("520"))

        # Yesterday's baseline must NOT be reused → new baseline from current equity
        assert baseline == Decimal("520")
        fake_events_repo.record_event.assert_called_once()
        call_args = fake_events_repo.record_event.call_args
        assert call_args.kwargs["event_type"] == "day_baseline_set"
        assert call_args.kwargs["context"]["date"] == today_str

    def test_no_prior_baseline_creates_new(self):
        """When no prior baseline event exists at all, create one from current equity."""
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _get_or_create_day_baseline

        fake_events_repo = MagicMock()
        fake_events_repo.get_latest_event_by_type.return_value = None

        fake_session = MagicMock()

        with patch(
            "trading.runtime.runner.EventsRepository",
            return_value=fake_events_repo,
        ):
            baseline = _get_or_create_day_baseline(fake_session, MagicMock(), Decimal("750"))

        assert baseline == Decimal("750")
        fake_events_repo.record_event.assert_called_once()
        call_args = fake_events_repo.record_event.call_args
        assert call_args.kwargs["event_type"] == "day_baseline_set"


class TestDataFreshness:
    """Regression tests for data_is_fresh calculation with naive and aware timestamps."""

    def _make_fake_portfolio(self) -> MagicMock:
        """Return a PortfolioAccount mock that returns safe decimal values."""
        portfolio = MagicMock()
        portfolio.total_equity.return_value = Decimal("500")
        portfolio.positions = {}
        return portfolio

    def test_data_is_fresh_naive_timestamp(self):
        """data_is_fresh handles naive datetime without raising TypeError."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _build_cycle_inputs

        # Simulate a candle with naive datetime (SQLite default)
        naive_ts = datetime(2020, 1, 1, 12, 0, 0)  # no tzinfo

        candle_mock = MagicMock()
        candle_mock.open_time = naive_ts
        candle_mock.close = Decimal("50000")

        candles_repo = MagicMock()
        candles_repo.get_latest.return_value = candle_mock

        exec_repo = MagicMock()
        exec_repo.list_fills_chronological.return_value = []
        exec_repo.list_recent_orders.return_value = []

        with patch("trading.runtime.runner.CandlesRepository", return_value=candles_repo):
            with patch("trading.runtime.runner.ExecutionRecordsRepository", return_value=exec_repo):
                with patch(
                    "trading.runtime.runner.PortfolioAccount",
                    return_value=self._make_fake_portfolio(),
                ):
                    # Must not raise TypeError even though naive_ts has no tzinfo
                    inputs = _build_cycle_inputs(
                        session=MagicMock(),
                        symbols=["BTCUSDT"],
                        now=datetime.now(UTC),
                        initial_cash_usdt=Decimal("500"),
                    )

        assert len(inputs) == 1
        # Naive timestamp far in the past → not fresh
        assert inputs[0].data_is_fresh is False

    def test_data_is_fresh_aware_timestamp_fresh(self):
        """data_is_fresh is True when aware timestamp is within the stale threshold."""
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _build_cycle_inputs

        # Recent aware UTC timestamp (within 30 min)
        recent_aware = datetime.now(UTC) - timedelta(minutes=5)

        candle_mock = MagicMock()
        candle_mock.open_time = recent_aware
        candle_mock.close = Decimal("50000")

        candles_repo = MagicMock()
        candles_repo.get_latest.return_value = candle_mock

        exec_repo = MagicMock()
        exec_repo.list_fills_chronological.return_value = []
        exec_repo.list_recent_orders.return_value = []

        with patch("trading.runtime.runner.CandlesRepository", return_value=candles_repo):
            with patch("trading.runtime.runner.ExecutionRecordsRepository", return_value=exec_repo):
                with patch(
                    "trading.runtime.runner.PortfolioAccount",
                    return_value=self._make_fake_portfolio(),
                ):
                    inputs = _build_cycle_inputs(
                        session=MagicMock(),
                        symbols=["BTCUSDT"],
                        now=datetime.now(UTC),
                        initial_cash_usdt=Decimal("500"),
                    )

        assert len(inputs) == 1
        assert inputs[0].data_is_fresh is True

    def test_data_is_fresh_aware_timestamp_stale(self):
        """data_is_fresh is False when aware timestamp is older than the threshold."""
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _build_cycle_inputs

        # Old aware UTC timestamp (more than 30 min ago)
        old_aware = datetime.now(UTC) - timedelta(minutes=45)

        candle_mock = MagicMock()
        candle_mock.open_time = old_aware
        candle_mock.close = Decimal("50000")

        candles_repo = MagicMock()
        candles_repo.get_latest.return_value = candle_mock

        exec_repo = MagicMock()
        exec_repo.list_fills_chronological.return_value = []
        exec_repo.list_recent_orders.return_value = []

        with patch("trading.runtime.runner.CandlesRepository", return_value=candles_repo):
            with patch("trading.runtime.runner.ExecutionRecordsRepository", return_value=exec_repo):
                with patch(
                    "trading.runtime.runner.PortfolioAccount",
                    return_value=self._make_fake_portfolio(),
                ):
                    inputs = _build_cycle_inputs(
                        session=MagicMock(),
                        symbols=["BTCUSDT"],
                        now=datetime.now(UTC),
                        initial_cash_usdt=Decimal("500"),
                    )

        assert len(inputs) == 1
        assert inputs[0].data_is_fresh is False

    def test_data_is_fresh_no_candles(self):
        """data_is_fresh is False when no candles are available."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from unittest.mock import MagicMock, patch

        from trading.runtime.runner import _build_cycle_inputs

        candles_repo = MagicMock()
        candles_repo.get_latest.return_value = None

        exec_repo = MagicMock()
        exec_repo.list_fills_chronological.return_value = []
        exec_repo.list_recent_orders.return_value = []

        with patch("trading.runtime.runner.CandlesRepository", return_value=candles_repo):
            with patch("trading.runtime.runner.ExecutionRecordsRepository", return_value=exec_repo):
                with patch(
                    "trading.runtime.runner.PortfolioAccount",
                    return_value=self._make_fake_portfolio(),
                ):
                    inputs = _build_cycle_inputs(
                        session=MagicMock(),
                        symbols=["BTCUSDT"],
                        now=datetime.now(UTC),
                        initial_cash_usdt=Decimal("500"),
                    )

        assert len(inputs) == 1
        assert inputs[0].data_is_fresh is False
