"""Unit tests for the paper trading cycle orchestrator."""

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from trading.ai.schemas import AIScoreResult
from trading.execution.gate import LiveTradingLock
from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.runtime.paper_cycle import CycleInput, run_paper_cycle
from trading.strategies.base import TradeCandidate

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_candidate(symbol: str = "BTCUSDT") -> TradeCandidate:
    return TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol=symbol,
        side="BUY",
        entry_reference=Decimal("100000"),
        stop_reference=Decimal("98000"),
        rule_confidence=Decimal("0.70"),
        reason="Test candidate.",
        created_at=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
    )


def make_input(
    symbol: str = "BTCUSDT",
    *,
    account_equity: Decimal = Decimal("500"),
    day_start_equity: Decimal = Decimal("500"),
    market_prices: dict | None = None,
    total_position_pct: Decimal = Decimal("0"),
    symbol_position_pct: Decimal = Decimal("0"),
    open_positions: int = 0,
    daily_order_count: int = 0,
    symbol_daily_trade_count: int = 0,
    consecutive_losses: int = 0,
    data_is_fresh: bool = True,
    kill_switch_enabled: bool = False,
) -> CycleInput:
    return CycleInput(
        symbol=symbol,
        now=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
        day_start_equity=day_start_equity,
        account_equity=account_equity,
        market_prices=market_prices or {symbol: Decimal("100000")},
        total_position_pct=total_position_pct,
        symbol_position_pct=symbol_position_pct,
        open_positions=open_positions,
        daily_order_count=daily_order_count,
        symbol_daily_trade_count=symbol_daily_trade_count,
        consecutive_losses=consecutive_losses,
        data_is_fresh=data_is_fresh,
        kill_switch_enabled=kill_switch_enabled,
    )


def make_ai_pass(ai_score: int = 80) -> AIScoreResult:
    return AIScoreResult(
        ai_score=ai_score,
        market_regime="trend",
        decision_hint="allow",
        risk_flags=[],
        explanation="Looks good.",
    )


def make_ai_reject(score: int = 0, hint: str = "reject") -> AIScoreResult:
    return AIScoreResult(
        ai_score=score,
        market_regime="unknown",
        decision_hint=hint,  # type: ignore[arg-type]
        risk_flags=["ai_error"],
        explanation="AI failed.",
    )


class FakeEventsRepo:
    def __init__(self) -> None:
        self.events: list[MagicMock] = []
        self._next_id = 1

    def record_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        context: dict | None = None,
    ) -> MagicMock:
        ev = MagicMock()
        ev.id = self._next_id
        self._next_id += 1
        ev.event_type = event_type
        ev.severity = severity
        ev.component = component
        ev.message = message
        ev.context_json = context or {}
        self.events.append(ev)
        return ev


class FakeExecRepo:
    def __init__(self) -> None:
        self.recorded: list[tuple] = []

    def record_paper_execution(
        self,
        order: PaperOrder,
        fill: PaperFill,
    ) -> tuple:
        self.recorded.append((order, fill))
        return order, fill


# ── Tests ─────────────────────────────────────────────────────────────────────


# Shared fake lock for paper_auto mode tests
_PAPER_LOCK = LiveTradingLock()


@contextmanager
def _paper_auto_patches():
    """Patch get_trade_mode and get_live_trading_lock for paper_auto mode."""
    with patch(
        "trading.runtime.paper_cycle.get_trade_mode", return_value="paper_auto"
    ), patch(
        "trading.runtime.paper_cycle.get_live_trading_lock", return_value=_PAPER_LOCK
    ):
        yield


def test_no_signal_path_returns_no_signal_and_no_execution():
    """When generate_momentum_candidate returns None, status is no_signal."""
    input_data = make_input()

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    executor = MagicMock()
    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch("trading.runtime.paper_cycle.get_trade_mode", return_value="paper_auto"):
            with patch(
                "trading.runtime.paper_cycle.get_live_trading_lock",
                return_value=_PAPER_LOCK,
            ):
                result = run_paper_cycle(
                    input_data,
                    events_repo=events_repo,
                    exec_repo=exec_repo,
                    executor=executor,
                    ai_scorer=ai_scorer,
                    session_factory=factory,
                )

    assert result.status == "no_signal"
    assert result.candidate_present is False
    assert result.order_executed is False
    assert result.ai_decision is None
    assert exec_repo.recorded == []

    # AI scorer should not be called when there is no candidate
    ai_scorer.score_candidate.assert_not_called()

    event_types = [ev.event_type for ev in events_repo.events]
    assert "cycle_started" in event_types
    assert "signal_generated" not in event_types
    assert "risk_rejected" not in event_types
    assert "order_executed" not in event_types
    assert "cycle_finished" in event_types


def test_risk_rejection_path_kill_switch():
    """When kill_switch is enabled, pre-trade risk rejects before execution."""
    input_data = make_input(kill_switch_enabled=True)

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    ai_scorer.score_candidate.return_value = make_ai_pass()
    executor = MagicMock()
    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch(
            "trading.runtime.paper_cycle.generate_momentum_candidate",
            return_value=make_candidate(),
        ):
            with _paper_auto_patches():
                result = run_paper_cycle(
                        input_data,
                        events_repo=events_repo,
                        exec_repo=exec_repo,
                        executor=executor,
                        ai_scorer=ai_scorer,
                        session_factory=factory,
                    )

    assert result.status == "risk_rejected"
    assert result.candidate_present is True
    assert result.order_executed is False
    assert "kill_switch_enabled" in result.reject_reasons
    assert exec_repo.recorded == []
    executor.execute_market_buy.assert_not_called()

    event_types = [ev.event_type for ev in events_repo.events]
    assert "cycle_started" in event_types
    assert "signal_generated" in event_types
    assert "risk_rejected" in event_types
    assert "order_executed" not in event_types


def test_ai_fail_closed_rejection_path():
    """When AI scoring fail-closes (reject hint or score < 50), no execution."""
    input_data = make_input()

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    ai_scorer.score_candidate.return_value = make_ai_reject(score=0, hint="reject")
    executor = MagicMock()
    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch(
            "trading.runtime.paper_cycle.generate_momentum_candidate",
            return_value=make_candidate(),
        ):
            with _paper_auto_patches():
                result = run_paper_cycle(
                        input_data,
                        events_repo=events_repo,
                        exec_repo=exec_repo,
                        executor=executor,
                        ai_scorer=ai_scorer,
                        session_factory=factory,
                    )

    assert result.status == "ai_rejected"
    assert result.candidate_present is True
    assert result.order_executed is False
    assert result.ai_decision is not None
    assert result.ai_decision["ai_score"] == 0
    assert any("ai_rejected" in r for r in result.reject_reasons)
    assert exec_repo.recorded == []
    executor.execute_market_buy.assert_not_called()

    event_types = [ev.event_type for ev in events_repo.events]
    assert "cycle_started" in event_types
    assert "signal_generated" in event_types
    assert "risk_rejected" in event_types  # ai_rejected maps to risk_rejected event
    assert "order_executed" not in event_types


def test_ai_low_score_rejected():
    """When AI score < 50 even with allow hint, reject (fail-closed)."""
    input_data = make_input()

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    ai_scorer.score_candidate.return_value = make_ai_pass(ai_score=35)
    executor = MagicMock()
    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch(
            "trading.runtime.paper_cycle.generate_momentum_candidate",
            return_value=make_candidate(),
        ):
            with _paper_auto_patches():
                result = run_paper_cycle(
                        input_data,
                        events_repo=events_repo,
                        exec_repo=exec_repo,
                        executor=executor,
                        ai_scorer=ai_scorer,
                        session_factory=factory,
                    )

    assert result.status == "ai_rejected"
    assert result.order_executed is False
    assert exec_repo.recorded == []


def test_successful_execution_with_persisted_order_and_fill():
    """When all checks pass, order is executed and persisted via repository."""
    input_data = make_input()

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    ai_scorer.score_candidate.return_value = make_ai_pass(ai_score=85)

    # Executor returns an approved result
    exec_order = PaperOrder(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        requested_notional_usdt=Decimal("100"),
        status="FILLED",
        created_at=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
    )
    exec_fill = PaperFill(
        symbol="BTCUSDT",
        side="BUY",
        price=Decimal("100000"),
        qty=Decimal("0.001"),
        fee_usdt=Decimal("0.25"),
        slippage_bps=Decimal("0"),
        filled_at=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
    )
    from trading.execution.paper_executor import PaperExecutionResult
    exec_result = PaperExecutionResult(
        approved=True,
        order=exec_order,
        fill=exec_fill,
        reject_reasons=[],
    )
    executor = MagicMock()
    executor.execute_market_buy.return_value = exec_result

    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch(
            "trading.runtime.paper_cycle.generate_momentum_candidate",
            return_value=make_candidate(),
        ):
            with _paper_auto_patches():
                result = run_paper_cycle(
                        input_data,
                        events_repo=events_repo,
                        exec_repo=exec_repo,
                        executor=executor,
                        ai_scorer=ai_scorer,
                        session_factory=factory,
                    )

    assert result.status == "executed"
    assert result.candidate_present is True
    assert result.order_executed is True
    assert result.ai_decision is not None
    assert result.ai_decision["ai_score"] == 85
    assert result.risk_state in ("normal", "degraded")
    assert result.reject_reasons == []

    # Order and fill should be persisted via ExecutionRecordsRepository
    assert len(exec_repo.recorded) == 1
    persisted_order, persisted_fill = exec_repo.recorded[0]
    assert persisted_order.symbol == "BTCUSDT"
    assert persisted_fill.symbol == "BTCUSDT"

    # Verify event sequence
    event_types = [ev.event_type for ev in events_repo.events]
    assert event_types == [
        "cycle_started",
        "signal_generated",
        "order_executed",
        "cycle_finished",
    ]

    # Verify ai_decision is stored in a cycle event
    signal_ev = next(ev for ev in events_repo.events if ev.event_type == "signal_generated")
    assert signal_ev.context_json["symbol"] == "BTCUSDT"

    executed_ev = next(ev for ev in events_repo.events if ev.event_type == "order_executed")
    assert executed_ev.context_json["symbol"] == "BTCUSDT"
    assert executed_ev.context_json["side"] == "BUY"


def test_position_size_rejection_stops_before_execution():
    """When position sizing rejects, executor is never called."""
    input_data = make_input()

    fake_session = MagicMock()
    fake_repo = MagicMock()
    fake_repo.list_recent.return_value = []
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=None)

    def factory() -> MagicMock:
        return fake_session

    ai_scorer = MagicMock()
    ai_scorer.score_candidate.return_value = make_ai_pass()

    # Position sizing will reject because entry_reference == stop_reference is invalid
    # (stop_distance <= 0 => position_size rejected)
    executor = MagicMock()
    events_repo = FakeEventsRepo()
    exec_repo = FakeExecRepo()

    # Candidate with equal entry and stop → invalid stop distance
    bad_candidate = TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("100000"),
        stop_reference=Decimal("100000"),  # same as entry → invalid
        rule_confidence=Decimal("0.70"),
        reason="Test.",
        created_at=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
    )

    with patch(
        "trading.runtime.paper_cycle.CandlesRepository",
        return_value=fake_repo,
    ):
        with patch(
            "trading.runtime.paper_cycle.generate_momentum_candidate",
            return_value=bad_candidate,
        ):
            with _paper_auto_patches():
                result = run_paper_cycle(
                        input_data,
                        events_repo=events_repo,
                        exec_repo=exec_repo,
                        executor=executor,
                        ai_scorer=ai_scorer,
                        session_factory=factory,
                    )

    assert result.status == "size_rejected"
    assert result.candidate_present is True
    assert result.order_executed is False
    is_size_rejected = (
        result.status == "size_rejected"
        or "invalid_stop_distance" in str(result.reject_reasons)
    )
    assert is_size_rejected
    assert exec_repo.recorded == []
    executor.execute_market_buy.assert_not_called()

    event_types = [ev.event_type for ev in events_repo.events]
    assert "cycle_started" in event_types
    assert "signal_generated" in event_types
    assert "risk_rejected" in event_types  # size rejection maps to risk_rejected event
    assert "order_executed" not in event_types
