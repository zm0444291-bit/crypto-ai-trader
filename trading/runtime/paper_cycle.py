"""Paper trading cycle orchestrator.

Stitch existing modules into one deterministic cycle:
market data -> features -> strategy candidate -> AI score
-> pre-trade risk -> position sizing -> paper execution
-> persistence -> runtime events.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trading.market_data.adapters.base import BidAskQuote
    from trading.market_data.schemas import CandleData

from pydantic import BaseModel
from sqlalchemy.orm import Session

from trading.market_data.adapters.base import BidAskQuote

from trading.ai.scorer import AIScorer
from trading.execution.gate import ExecutionGate
from trading.execution.paper_executor import PaperExecutionResult, PaperExecutor
from trading.features.builder import CandleFeatures, build_features
from trading.portfolio.accounting import Position
from trading.risk.position_sizing import PositionSizeResult, calculate_position_size
from trading.risk.pre_trade import (
    PortfolioRiskSnapshot,
    PreTradeRiskDecision,
    evaluate_pre_trade_risk,
)
from trading.risk.profiles import select_risk_profile
from trading.runtime.state import get_live_trading_lock, get_trade_mode
from trading.storage.repositories import (
    CandlesRepository,
    EventsRepository,
    ExecutionRecordsRepository,
    ShadowExecutionRepository,
)
from trading.strategies.active.multi_timeframe_momentum import (
    generate_momentum_candidate,
)
from trading.strategies.active.strategy_selector import StrategySelector
from trading.strategies.exits import ExitEngine, ExitSignal

# ── Lifecycle stages ──────────────────────────────────────────────────────────

LIFECYCLE_STAGES = (
    "cycle_started",
    "signal_received",
    "risk_checked",
    "position_sized",
    "execution_attempted",
    "execution_result",
    "no_execution",
    "exit_evaluated",
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _orm_candle_to_data(candle: Any) -> "CandleData":
    """Convert an ORM Candle row to a CandleData for build_features."""
    from trading.market_data.schemas import CandleData

    return CandleData(
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        open_time=candle.open_time,
        close_time=candle.close_time,
        open=Decimal(str(candle.open)),
        high=Decimal(str(candle.high)),
        low=Decimal(str(candle.low)),
        close=Decimal(str(candle.close)),
        volume=Decimal(str(candle.volume)),
        source=candle.source or "binance",
    )


def _record_lifecycle(
    events_repo: EventsRepository,
    trace_id: str,
    cycle_id: str,
    symbol: str,
    side: str | None,
    mode: str,
    stage: str,
    event_type: str,
    severity: str,
    component: str,
    message: str,
    context: dict[str, Any] | None = None,
    reason: str | None = None,
) -> int:
    """Record a lifecycle event and return its id."""
    ev = events_repo.record_event(
        event_type=event_type,
        severity=severity,
        component=component,
        message=message,
        context=context,
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=symbol,
        side=side,
        mode=mode,
        lifecycle_stage=stage,
        reason=reason,
    )
    return ev.id


# ── Models ──────────────────────────────────────────────────────────────────────


class CycleInput(BaseModel):
    """Input for a single paper trading cycle for one symbol."""

    symbol: str
    now: datetime
    day_start_equity: Decimal
    account_equity: Decimal
    market_prices: dict[str, Decimal]
    # Optional real-time bid/ask quotes for precise execution pricing.
    # When provided, execution uses bid/ask instead of mid price.
    bid_ask_quotes: dict[str, "BidAskQuote"] | None = None
    total_position_pct: Decimal
    symbol_position_pct: Decimal
    open_positions: int
    daily_order_count: int
    symbol_daily_trade_count: int
    consecutive_losses: int
    data_is_fresh: bool
    kill_switch_enabled: bool
    # Open position for this symbol (if any); used for exit scanning
    current_position: Position | None = None


class CycleResult(BaseModel):
    """Result of one paper trading cycle."""

    symbol: str
    status: str
    candidate_present: bool
    ai_decision: dict[str, Any] | None
    risk_state: str | None
    order_executed: bool
    reject_reasons: list[str]
    event_ids: list[int]
    # Exit result
    exit_signal: ExitSignal | None = None
    exit_executed: bool = False
    # Correlation IDs for audit chain
    trace_id: str | None = None
    cycle_id: str | None = None


# ── Exit helpers ────────────────────────────────────────────────────────────────


def _run_exit_scan(
    input_data: CycleInput,
    exit_engine: ExitEngine,
    executor: PaperExecutor,
    events_repo: EventsRepository,
    exec_repo: ExecutionRecordsRepository,
    trace_id: str,
    cycle_id: str,
    mode: str,
) -> tuple[ExitSignal | None, bool, list[int]]:
    """Scan for and optionally execute exit signals on the current position.

    Returns (exit_signal, exit_executed, new_event_ids).
    """
    event_ids: list[int] = []
    position = input_data.current_position

    if position is None or position.qty <= Decimal("0"):
        return None, False, event_ids

    market_price = input_data.market_prices.get(input_data.symbol)
    if market_price is None:
        return None, False, event_ids

    # Use bid/ask quote for execution when available, otherwise fall back to mid
    exec_price: BidAskQuote | Decimal = (
        input_data.bid_ask_quotes.get(input_data.symbol, market_price)
        if input_data.bid_ask_quotes is not None
        else market_price
    )

    # ── exit_evaluated (signal found) ─────────────────────────────────────
    exit_signal = exit_engine.evaluate(
        symbol=input_data.symbol,
        position_qty=position.qty,
        position_avg_entry=position.avg_entry_price,
        position_stop=position.stop_reference,
        position_entry_atr=position.entry_atr,
        market_price=market_price,
        current_time=input_data.now,
        position_opened_at=position.opened_at or input_data.now,
    )

    if exit_signal is None:
        _record_lifecycle(
            events_repo=events_repo,
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side="SELL",
            mode=mode,
            stage="exit_evaluated",
            event_type="exit_evaluated",
            severity="info",
            component="paper_cycle",
            message=f"Exit scan for {input_data.symbol}: no signal.",
            context={
                "position_qty": str(position.qty),
                "market_price": str(market_price),
            },
        )
        return None, False, event_ids

    # Record exit_signal_generated event with full lifecycle fields
    exit_gen_ev = events_repo.record_event(
        event_type="exit_signal_generated",
        severity="info",
        component="paper_cycle",
        message=(
            f"Exit signal for {input_data.symbol}:"
            f" {exit_signal.reason.value} @ {exit_signal.exit_price}"
        ),
        context={
            "symbol": input_data.symbol,
            "reason": exit_signal.reason.value,
            "exit_price": str(exit_signal.exit_price),
            "qty_to_exit": str(exit_signal.qty_to_exit),
            "confidence": str(exit_signal.confidence),
            "message": exit_signal.message,
        },
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side="SELL",
        mode=mode,
        lifecycle_stage="exit_evaluated",
        reason=exit_signal.reason.value,
    )
    event_ids.append(exit_gen_ev.id)

    # Execute the sell — use bid/ask quote for precise pricing
    exec_result = executor.execute_market_sell(
        symbol=input_data.symbol,
        qty=exit_signal.qty_to_exit,
        market_price=exec_price,
        executed_at=input_data.now,
    )

    if exec_result.approved and exec_result.order is not None and exec_result.fill is not None:
        exec_repo.record_paper_execution(
            order=exec_result.order,
            fill=exec_result.fill,
        )
        executed_ev = events_repo.record_event(
            event_type="order_executed",
            severity="info",
            component="paper_cycle",
            message=(
                f"Paper SELL {exit_signal.qty_to_exit} {input_data.symbol}"
                f" @ {exec_result.fill.price}"
                f" (reason={exit_signal.reason.value})"
            ),
            context={
                "symbol": input_data.symbol,
                "side": "SELL",
                "qty": str(exit_signal.qty_to_exit),
                "price": str(exec_result.fill.price) if exec_result.fill else None,
                "fee_usdt": str(exec_result.fill.fee_usdt),
                "reason": exit_signal.reason.value,
                "notional": str(exec_result.order.requested_notional_usdt),
            },
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side="SELL",
            mode=mode,
            lifecycle_stage="execution_result",
            reason=exit_signal.reason.value,
        )
        event_ids.append(executed_ev.id)

    return exit_signal, exec_result.approved, event_ids


# ── Cycle ──────────────────────────────────────────────────────────────────────


def run_paper_cycle(
    input_data: CycleInput,
    events_repo: EventsRepository,
    exec_repo: ExecutionRecordsRepository,
    executor: PaperExecutor,
    ai_scorer: AIScorer,
    session_factory: Callable[[], Session],
    min_notional_usdt: Decimal = Decimal("10"),
    exit_engine: ExitEngine | None = None,
    strategy_selector: StrategySelector | None = None,
) -> CycleResult:
    """Run a full paper trading cycle for one symbol.

    Pipeline:
        0. cycle_started + exit scan (if current_position set and exit_engine provided)
        1. candles -> features
        2. features -> strategy candidate
        3. signal_received -> AI score  (fail-closed)
        4. risk_checked (AI reject path)
        5. pre-trade risk check
        6. risk_checked (risk reject path) -> position_sized
        7. execution_attempted (gate check) -> execution_result
        8. persist order/fill
        9. record events
    """

    # Generate correlation IDs at cycle start
    trace_id = str(uuid.uuid4().hex[:16])
    cycle_id = f"{input_data.symbol}-{input_data.now.strftime('%Y%m%d%H%M%S')}"
    mode = get_trade_mode(session_factory)
    side: str | None = None

    event_ids: list[int] = []
    reject_reasons: list[str] = []
    candidate_present = False
    ai_decision: dict[str, Any] | None = None
    risk_state: str | None = None
    order_executed = False
    exit_signal: ExitSignal | None = None
    exit_executed = False

    # ── Stage 0: cycle_started (lifecycle_stage=cycle_started) ─────────────────
    started = events_repo.record_event(
        event_type="cycle_started",
        severity="info",
        component="paper_cycle",
        message=f"Paper cycle started for {input_data.symbol}",
        context={
            "symbol": input_data.symbol,
            "account_equity": str(input_data.account_equity),
            "day_start_equity": str(input_data.day_start_equity),
            "kill_switch": input_data.kill_switch_enabled,
        },
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=None,
        mode=mode,
        lifecycle_stage="cycle_started",
        reason=None,
    )
    event_ids.append(started.id)

    # ── Stage 0b: exit scan (before entry) ───────────────────────────────────
    if exit_engine is not None and input_data.current_position is not None:
        (
            exit_signal,
            exit_executed,
            exit_event_ids,
        ) = _run_exit_scan(
            input_data=input_data,
            exit_engine=exit_engine,
            executor=executor,
            events_repo=events_repo,
            exec_repo=exec_repo,
            trace_id=trace_id,
            cycle_id=cycle_id,
            mode=mode,
        )
        event_ids.extend(exit_event_ids)

        if exit_executed:
            # Position was closed — still record cycle_finished and return
            finished = events_repo.record_event(
                event_type="cycle_finished",
                severity="info",
                component="paper_cycle",
                message=f"Exit executed for {input_data.symbol}; skipping entry scan.",
                context={
                    "status": "exit_executed",
                    "symbol": input_data.symbol,
                    "exit_reason": exit_signal.reason.value if exit_signal else None,
                },
                trace_id=trace_id,
                cycle_id=cycle_id,
                symbol=input_data.symbol,
                side="SELL",
                mode=mode,
                lifecycle_stage="execution_result",
                reason=exit_signal.reason.value if exit_signal else "exit_executed",
            )
            event_ids.append(finished.id)
            return CycleResult(
                symbol=input_data.symbol,
                status="exit_executed",
                candidate_present=False,
                ai_decision=None,
                risk_state=None,
                order_executed=False,
                reject_reasons=[],
                event_ids=event_ids,
                exit_signal=exit_signal,
                exit_executed=True,
                trace_id=trace_id,
                cycle_id=cycle_id,
            )

    # ── Stage 1: fetch candles and build features ───────────────────────────
    with session_factory() as session:
        repo = CandlesRepository(session)
        candles_15m = repo.list_recent(input_data.symbol, "15m", limit=100)
        candles_1h = repo.list_recent(input_data.symbol, "1h", limit=100)
        candles_4h = repo.list_recent(input_data.symbol, "4h", limit=100)

        features_15m = build_features([_orm_candle_to_data(c) for c in candles_15m])
        features_1h = build_features([_orm_candle_to_data(c) for c in candles_1h])
        features_4h = build_features([_orm_candle_to_data(c) for c in candles_4h])

    # ── Stage 2: strategy candidate (via StrategySelector with regime routing) ────
    # Default to legacy momentum if no selector provided (backwards compatibility)
    if strategy_selector is not None:
        candidate = strategy_selector.select_candidate(
            symbol=input_data.symbol,
            features_15m=features_15m,
            features_1h=features_1h,
            features_4h=features_4h,
            now=input_data.now,
        )
    else:
        # Legacy fallback — single momentum strategy (backwards compat only)
        candidate = generate_momentum_candidate(
            symbol=input_data.symbol,
            features_15m=features_15m,
            features_1h=features_1h,
            features_4h=features_4h,
            now=input_data.now,
        )

    if candidate is None:
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"No signal for {input_data.symbol}",
            context={"status": "no_signal"},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=None,
            mode=mode,
            lifecycle_stage="signal_received",
            reason="no_candidate",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="no_signal",
            candidate_present=False,
            ai_decision=None,
            risk_state=None,
            order_executed=False,
            reject_reasons=[],
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    candidate_present = True
    side = candidate.side

    # ── Stage 3a: signal_received (lifecycle stage) ──────────────────────────
    signal_ev = events_repo.record_event(
        event_type="signal_generated",
        severity="info",
        component="paper_cycle",
        message=f"Candidate generated for {input_data.symbol}: {candidate.reason}",
        context={
            "symbol": input_data.symbol,
            "side": candidate.side,
            "entry_reference": str(candidate.entry_reference),
            "rule_confidence": str(candidate.rule_confidence),
        },
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=candidate.side,
        mode=mode,
        lifecycle_stage="signal_received",
        reason=None,
    )
    event_ids.append(signal_ev.id)

    # ── Stage 3b: AI scoring (fail-closed) ───────────────────────────────────
    latest_15m: CandleFeatures | None = features_15m[-1] if features_15m else None

    ai_result = ai_scorer.score_candidate(
        candidate=candidate,
        market_context={
            "symbol": input_data.symbol,
            "trend_15m": latest_15m.trend_state if latest_15m else "unknown",
            "trend_1h": features_1h[-1].trend_state if features_1h else "unknown",
            "trend_4h": features_4h[-1].trend_state if features_4h else "unknown",
            "rsi_14": str(latest_15m.rsi_14) if latest_15m and latest_15m.rsi_14 else None,
        },
        portfolio_context={
            "account_equity": str(input_data.account_equity),
            "total_position_pct": str(input_data.total_position_pct),
            "symbol_position_pct": str(input_data.symbol_position_pct),
            "consecutive_losses": input_data.consecutive_losses,
        },
    )

    ai_decision = ai_result.model_dump()

    if ai_result.decision_hint == "reject" or ai_result.ai_score < 50:
        reject_reasons = [f"ai_rejected(score={ai_result.ai_score})", *ai_result.risk_flags]

        events_repo.record_event(
            event_type="risk_rejected",
            severity="warning",
            component="paper_cycle",
            message=f"AI rejected {input_data.symbol}: {ai_result.explanation}",
            context={"ai_decision": ai_decision, "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="risk_checked",
            reason="ai_rejected",
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle rejected by AI for {input_data.symbol}",
            context={"status": "ai_rejected", "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="risk_checked",
            reason="ai_rejected",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="ai_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=None,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    # AI passed — emit risk_checked (approved)
    _record_lifecycle(
        events_repo=events_repo,
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=side,
        mode=mode,
        stage="risk_checked",
        event_type="risk_checked",
        severity="info",
        component="paper_cycle",
        message=f"AI approved {input_data.symbol} (score={ai_result.ai_score})",
        context={
            "ai_score": ai_result.ai_score,
            "decision_hint": ai_result.decision_hint,
            "ai_explanation": ai_result.explanation,
        },
        reason="ai_approved",
    )

    # ── Stage 4: pre-trade risk ─────────────────────────────────────────────
    risk_profile = select_risk_profile(input_data.account_equity)
    snapshot = PortfolioRiskSnapshot(
        account_equity=input_data.account_equity,
        day_start_equity=input_data.day_start_equity,
        total_position_pct=input_data.total_position_pct,
        symbol_position_pct=input_data.symbol_position_pct,
        open_positions=input_data.open_positions,
        daily_order_count=input_data.daily_order_count,
        symbol_daily_trade_count=input_data.symbol_daily_trade_count,
        consecutive_losses=input_data.consecutive_losses,
        data_is_fresh=input_data.data_is_fresh,
        kill_switch_enabled=input_data.kill_switch_enabled,
    )
    pre_trade: PreTradeRiskDecision = evaluate_pre_trade_risk(
        candidate=candidate,
        snapshot=snapshot,
        profile=risk_profile,
    )
    risk_state = pre_trade.risk_state

    if not pre_trade.approved:
        reject_reasons = ["risk_rejected", *pre_trade.reject_reasons]
        events_repo.record_event(
            event_type="risk_rejected",
            severity="warning",
            component="paper_cycle",
            message=f"Pre-trade risk rejected {input_data.symbol}: {pre_trade.reject_reasons}",
            context={"risk_state": risk_state, "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="risk_checked",
            reason="risk_rejected",
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle risk-rejected for {input_data.symbol}",
            context={"status": "risk_rejected", "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="risk_checked",
            reason="risk_rejected",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="risk_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    # ── Stage 5: position sizing ─────────────────────────────────────────────
    market_price = input_data.market_prices.get(input_data.symbol)
    if market_price is None:
        reject_reasons = ["missing_market_price"]
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="warning",
            component="paper_cycle",
            message=f"No market price for {input_data.symbol}",
            context={"status": "size_rejected", "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="position_sized",
            reason="missing_market_price",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="size_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    size_result: PositionSizeResult = calculate_position_size(
        candidate=candidate,
        pre_trade_decision=pre_trade,
        profile=risk_profile,
        account_equity=input_data.account_equity,
        min_notional_usdt=min_notional_usdt,
    )

    if not size_result.approved:
        reject_reasons = ["position_size_rejected", *size_result.reject_reasons]
        events_repo.record_event(
            event_type="risk_rejected",
            severity="warning",
            component="paper_cycle",
            message=f"Position sizing rejected {input_data.symbol}: {size_result.reject_reasons}",
            context={"reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="position_sized",
            reason="position_size_rejected",
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle size-rejected for {input_data.symbol}",
            context={"status": "size_rejected", "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="position_sized",
            reason="position_size_rejected",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="size_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    # Position sizing approved — emit position_sized lifecycle event
    _record_lifecycle(
        events_repo=events_repo,
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=side,
        mode=mode,
        stage="position_sized",
        event_type="position_sized",
        severity="info",
        component="paper_cycle",
        message=f"Position sized for {input_data.symbol}: {size_result.notional_usdt} USDT",
        context={
            "notional_usdt": str(size_result.notional_usdt),
            "max_loss_usdt": str(size_result.max_loss_usdt),
        },
        reason=None,
    )

    # ── Stage 6: execution gate ──────────────────────────────────────────────
    gate = ExecutionGate()
    lock = get_live_trading_lock(session_factory)
    gate_decision = gate.decide(
        mode=mode,
        lock=lock,
        risk_approved=pre_trade.approved,
        kill_switch_enabled=input_data.kill_switch_enabled,
        candidate_symbol=candidate.symbol,
    )

    # Emit execution_attempted lifecycle event (gate decision made)
    _record_lifecycle(
        events_repo=events_repo,
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=side,
        mode=mode,
        stage="execution_attempted",
        event_type="execution_attempted",
        severity="info",
        component="paper_cycle",
        message=f"Execution gate decision for {input_data.symbol}: {gate_decision.route}",
        context={
            "gate_route": gate_decision.route,
            "gate_reason": gate_decision.reason,
            "gate_allowed": gate_decision.allowed,
        },
        reason=gate_decision.reason if not gate_decision.allowed else None,
    )

    if not gate_decision.allowed:
        reject_reasons = [f"execution_gate:{gate_decision.reason}"]
        events_repo.record_event(
            event_type="execution_gate_blocked",
            severity="warning",
            component="paper_cycle",
            message=f"Execution gate blocked {input_data.symbol}: {gate_decision.reason}",
            context={
                "mode": gate_decision.mode,
                "route": gate_decision.route,
                "reason": gate_decision.reason,
            },
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_attempted",
            reason=f"execution_gate:{gate_decision.reason}",
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle blocked by execution gate for {input_data.symbol}",
            context={"status": "gate_blocked", "reject_reasons": reject_reasons},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_attempted",
            reason=f"execution_gate:{gate_decision.reason}",
        )
        event_ids.append(finished.id)
        return CycleResult(
            symbol=input_data.symbol,
            status="gate_blocked",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    # ── Stage 7a: shadow execution (live_shadow mode) ────────────────────────
    if gate_decision.route == "shadow":
        simulated_fill_price = market_price * (
            Decimal("1") + executor._slippage_bps(candidate.symbol) / Decimal("10000")
        )
        with session_factory() as shadow_session:
            shadow_repo = ShadowExecutionRepository(shadow_session)
            shadow_repo.record_shadow_execution(
                symbol=candidate.symbol,
                side=candidate.side,
                planned_notional_usdt=size_result.notional_usdt,
                reference_price=market_price,
                simulated_fill_price=simulated_fill_price,
                simulated_slippage_bps=executor._slippage_bps(candidate.symbol),
                decision_reason=ai_result.explanation,
                source_cycle_status="shadow_recorded",
            )

        shadow_ev = events_repo.record_event(
            event_type="shadow_execution_recorded",
            severity="info",
            component="paper_cycle",
            message=(
                f"Shadow {candidate.side} {size_result.notional_usdt} {candidate.symbol}"
                f" @ {simulated_fill_price}"
            ),
            context={
                "symbol": candidate.symbol,
                "side": candidate.side,
                "planned_notional_usdt": str(size_result.notional_usdt),
                "reference_price": str(market_price),
                "simulated_fill_price": str(simulated_fill_price),
                "simulated_slippage_bps": str(executor._slippage_bps(candidate.symbol)),
                "execution_route": gate_decision.route,
            },
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_result",
            reason="live_shadow",
        )
        event_ids.append(shadow_ev.id)

        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Shadow cycle completed for {input_data.symbol}",
            context={"status": "shadow_recorded"},
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_result",
            reason="live_shadow",
        )
        event_ids.append(finished.id)

        return CycleResult(
            symbol=input_data.symbol,
            status="shadow_recorded",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=[],
            event_ids=event_ids,
            exit_signal=exit_signal,
            exit_executed=exit_executed,
            trace_id=trace_id,
            cycle_id=cycle_id,
        )

    # ── Stage 7b: paper execution ─────────────────────────────────────────────
    # Resolve bid/ask quote for precise execution pricing when available
    exec_price: BidAskQuote | Decimal = (
        input_data.bid_ask_quotes.get(input_data.symbol, market_price)
        if input_data.bid_ask_quotes is not None
        else market_price
    )
    exec_result: PaperExecutionResult = executor.execute_market_buy(
        candidate=candidate,
        position_size=size_result,
        market_price=exec_price,
        executed_at=input_data.now,
    )

    # ── Stage 8: persist order/fill ─────────────────────────────────────────
    if exec_result.approved and exec_result.order is not None and exec_result.fill is not None:
        exec_repo.record_paper_execution(
            order=exec_result.order,
            fill=exec_result.fill,
        )
        order_executed = True

        executed_ev = events_repo.record_event(
            event_type="order_executed",
            severity="info",
            component="paper_cycle",
            message=(
                f"Paper BUY {exec_result.fill.qty} {candidate.symbol}"
                f" @ {exec_result.fill.price}"
                f" (notional={exec_result.order.requested_notional_usdt})"
            ),
            context={
                "symbol": candidate.symbol,
                "side": candidate.side,
                "qty": str(exec_result.fill.qty),
                "price": str(exec_result.fill.price),
                "fee_usdt": str(exec_result.fill.fee_usdt),
                "notional": str(exec_result.order.requested_notional_usdt),
                "execution_route": gate_decision.route,
            },
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_result",
            reason=None,
        )
        event_ids.append(executed_ev.id)
    else:
        # Paper execution was not approved — emit execution_result with failure reason
        fail_reason = (
            exec_result.reject_reasons[0]
            if exec_result.reject_reasons
            else "execution_rejected"
        )
        events_repo.record_event(
            event_type="execution_result",
            severity="warning",
            component="paper_cycle",
            message=f"Paper execution rejected for {input_data.symbol}: {fail_reason}",
            context={
                "symbol": input_data.symbol,
                "reject_reasons": exec_result.reject_reasons,
                "execution_route": gate_decision.route,
            },
            trace_id=trace_id,
            cycle_id=cycle_id,
            symbol=input_data.symbol,
            side=side,
            mode=mode,
            lifecycle_stage="execution_result",
            reason=fail_reason,
        )

    # ── Stage 9: cycle_finished ─────────────────────────────────────────────
    finished = events_repo.record_event(
        event_type="cycle_finished",
        severity="info",
        component="paper_cycle",
        message=f"Paper cycle completed for {input_data.symbol}",
        context={
            "status": "executed" if order_executed else "no_execution",
            "order_executed": order_executed,
        },
        trace_id=trace_id,
        cycle_id=cycle_id,
        symbol=input_data.symbol,
        side=side,
        mode=mode,
        lifecycle_stage="execution_result" if order_executed else "no_execution",
        reason=None,
    )
    event_ids.append(finished.id)

    return CycleResult(
        symbol=input_data.symbol,
        status="executed" if order_executed else "no_execution",
        candidate_present=candidate_present,
        ai_decision=ai_decision,
        risk_state=risk_state,
        order_executed=order_executed,
        reject_reasons=[],
        event_ids=event_ids,
        exit_signal=exit_signal,
        exit_executed=exit_executed,
        trace_id=trace_id,
        cycle_id=cycle_id,
    )