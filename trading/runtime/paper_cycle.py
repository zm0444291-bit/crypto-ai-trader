"""Paper trading cycle orchestrator.

Stitch existing modules into one deterministic cycle:
market data -> features -> strategy candidate -> AI score
-> pre-trade risk -> position sizing -> paper execution
-> persistence -> runtime events.
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from trading.ai.scorer import AIScorer
from trading.execution.paper_executor import PaperExecutionResult, PaperExecutor
from trading.features.builder import CandleFeatures, build_features
from trading.risk.position_sizing import PositionSizeResult, calculate_position_size
from trading.risk.pre_trade import (
    PortfolioRiskSnapshot,
    PreTradeRiskDecision,
    evaluate_pre_trade_risk,
)
from trading.risk.profiles import select_risk_profile
from trading.storage.repositories import (
    CandlesRepository,
    EventsRepository,
    ExecutionRecordsRepository,
)
from trading.strategies.active.multi_timeframe_momentum import (
    generate_momentum_candidate,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _orm_candle_to_data(candle: Any):
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


# ── Models ────────────────────────────────────────────────────────────────────


class CycleInput(BaseModel):
    """Input for a single paper trading cycle for one symbol."""

    symbol: str
    now: datetime
    day_start_equity: Decimal
    account_equity: Decimal
    market_prices: dict[str, Decimal]
    total_position_pct: Decimal
    symbol_position_pct: Decimal
    open_positions: int
    daily_order_count: int
    symbol_daily_trade_count: int
    consecutive_losses: int
    data_is_fresh: bool
    kill_switch_enabled: bool


class CycleResult(BaseModel):
    """Result of one paper trading cycle."""

    status: str
    candidate_present: bool
    ai_decision: dict[str, Any] | None
    risk_state: str | None
    order_executed: bool
    reject_reasons: list[str]
    event_ids: list[int]


# ── Cycle ──────────────────────────────────────────────────────────────────────


def run_paper_cycle(
    input_data: CycleInput,
    events_repo: EventsRepository,
    exec_repo: ExecutionRecordsRepository,
    executor: PaperExecutor,
    ai_scorer: AIScorer,
    session_factory: Callable[[], Session],
    min_notional_usdt: Decimal = Decimal("10"),
) -> CycleResult:
    """Run a full paper trading cycle for one symbol.

    Pipeline:
        1. candles -> features
        2. features -> strategy candidate
        3. candidate -> AI score  (fail-closed)
        4. pre-trade risk check
        5. position sizing
        6. paper execution
        7. persist order/fill
        8. record events
    """

    event_ids: list[int] = []
    reject_reasons: list[str] = []
    candidate_present = False
    ai_decision: dict[str, Any] | None = None
    risk_state: str | None = None
    order_executed = False

    # ── Stage 1: cycle_started ───────────────────────────────────────────────
    started = events_repo.record_event(
        event_type="cycle_started",
        severity="info",
        component="paper_cycle",
        message=f"Paper cycle started for {input_data.symbol}",
        context={
            "symbol": input_data.symbol,
            "account_equity": str(input_data.account_equity),
            "day_start_equity": str(input_data.day_start_equity),
        },
    )
    event_ids.append(started.id)

    # ── Stage 2: fetch candles and build features ───────────────────────────
    with session_factory() as session:
        repo = CandlesRepository(session)
        candles_15m = repo.list_recent(input_data.symbol, "15m", limit=100)
        candles_1h = repo.list_recent(input_data.symbol, "1h", limit=100)
        candles_4h = repo.list_recent(input_data.symbol, "4h", limit=100)

        features_15m = build_features([_orm_candle_to_data(c) for c in candles_15m])
        features_1h = build_features([_orm_candle_to_data(c) for c in candles_1h])
        features_4h = build_features([_orm_candle_to_data(c) for c in candles_4h])

    # ── Stage 3: strategy candidate ──────────────────────────────────────────
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
        )
        event_ids.append(finished.id)
        return CycleResult(
            status="no_signal",
            candidate_present=False,
            ai_decision=None,
            risk_state=None,
            order_executed=False,
            reject_reasons=[],
            event_ids=event_ids,
        )

    candidate_present = True

    # ── Stage 4: signal_generated event ─────────────────────────────────────
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
    )
    event_ids.append(signal_ev.id)

    # ── Stage 5: AI scoring (fail-closed) ────────────────────────────────────
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
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle rejected by AI for {input_data.symbol}",
            context={"status": "ai_rejected", "reject_reasons": reject_reasons},
        )
        event_ids.append(finished.id)
        return CycleResult(
            status="ai_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=None,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
        )

    # ── Stage 6: pre-trade risk ─────────────────────────────────────────────
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
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle risk-rejected for {input_data.symbol}",
            context={"status": "risk_rejected", "reject_reasons": reject_reasons},
        )
        event_ids.append(finished.id)
        return CycleResult(
            status="risk_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
        )

    # ── Stage 7: position sizing ─────────────────────────────────────────────
    market_price = input_data.market_prices.get(input_data.symbol)
    if market_price is None:
        reject_reasons = ["missing_market_price"]
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="warning",
            component="paper_cycle",
            message=f"No market price for {input_data.symbol}",
            context={"status": "size_rejected", "reject_reasons": reject_reasons},
        )
        event_ids.append(finished.id)
        return CycleResult(
            status="size_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
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
        )
        finished = events_repo.record_event(
            event_type="cycle_finished",
            severity="info",
            component="paper_cycle",
            message=f"Cycle size-rejected for {input_data.symbol}",
            context={"status": "size_rejected", "reject_reasons": reject_reasons},
        )
        event_ids.append(finished.id)
        return CycleResult(
            status="size_rejected",
            candidate_present=candidate_present,
            ai_decision=ai_decision,
            risk_state=risk_state,
            order_executed=False,
            reject_reasons=reject_reasons,
            event_ids=event_ids,
        )

    # ── Stage 8: paper execution ─────────────────────────────────────────────
    exec_result: PaperExecutionResult = executor.execute_market_buy(
        candidate=candidate,
        position_size=size_result,
        market_price=market_price,
        executed_at=input_data.now,
    )

    # ── Stage 9: persist order/fill ─────────────────────────────────────────
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
            },
        )
        event_ids.append(executed_ev.id)

    # ── Stage 10: cycle_finished ─────────────────────────────────────────────
    finished = events_repo.record_event(
        event_type="cycle_finished",
        severity="info",
        component="paper_cycle",
        message=f"Paper cycle completed for {input_data.symbol}",
        context={
            "status": "executed" if order_executed else "no_execution",
            "order_executed": order_executed,
        },
    )
    event_ids.append(finished.id)

    return CycleResult(
        status="executed" if order_executed else "no_execution",
        candidate_present=candidate_present,
        ai_decision=ai_decision,
        risk_state=risk_state,
        order_executed=order_executed,
        reject_reasons=[],
        event_ids=event_ids,
    )
