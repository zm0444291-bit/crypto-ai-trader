"""Runtime service for executing paper trading cycles locally."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event as ThreadingEvent

from sqlalchemy.orm import Session

from trading.ai.scorer import AIScorer
from trading.execution.paper_executor import PaperExecutor
from trading.market_data.candle_service import SYMBOLS
from trading.notifications.base import NotificationContext, NotificationLevel, Notifier
from trading.notifications.log_notifier import LogNotifier
from trading.portfolio.accounting import PortfolioAccount
from trading.runtime.paper_cycle import CycleInput, CycleResult, run_paper_cycle
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.models import Candle
from trading.storage.repositories import (
    CandlesRepository,
    EventsRepository,
    ExecutionRecordsRepository,
)

logger = logging.getLogger(__name__)

# Default paper executor config
DEFAULT_FEE_BPS = Decimal("10")
DEFAULT_SLIPPAGE_BPS = Decimal("0")
DEFAULT_MIN_NOTIONAL = Decimal("10")


def _get_or_create_day_baseline(
    session: Session, now: datetime, current_equity: Decimal
) -> Decimal:
    """Return today's opening equity baseline, creating one if it doesn't exist.

    The baseline is stored as a `day_baseline_set` event keyed by UTC date.
    Within the same UTC day the baseline is reused; a new baseline is created
    on the first cycle of each new UTC day.
    """
    today_utc = now.date()
    events_repo = EventsRepository(session)

    # Find most recent baseline event
    for event in events_repo.list_recent(limit=100):
        if event.event_type != "day_baseline_set":
            continue
        # event.context_json has {date: "YYYY-MM-DD", baseline: "..."}
        ctx = event.context_json or {}
        if ctx.get("date") == str(today_utc):
            return Decimal(str(ctx["baseline"]))

    # No baseline for today — create one using current equity
    baseline = max(current_equity, Decimal("0"))
    events_repo.record_event(
        event_type="day_baseline_set",
        severity="info",
        component="runner",
        message=f"Daily equity baseline set: {baseline}",
        context={"date": str(today_utc), "baseline": str(baseline)},
    )
    return baseline


def _build_cycle_inputs(
    session: Session,
    symbols: list[str],
    now: datetime,
    initial_cash_usdt: Decimal,
) -> list[CycleInput]:
    """Build CycleInput for each symbol using live DB state."""

    exec_repo = ExecutionRecordsRepository(session)
    candles_repo = CandlesRepository(session)

    # Rebuild portfolio from historical fills
    account = PortfolioAccount(cash_balance=initial_cash_usdt)
    for fill in exec_repo.list_fills_chronological():

        from trading.execution.paper_executor import PaperFill

        pf = PaperFill(
            symbol=fill.symbol,
            side=fill.side,
            price=fill.price,
            qty=fill.qty,
            fee_usdt=fill.fee_usdt,
            slippage_bps=fill.slippage_bps,
            filled_at=fill.filled_at,
        )
        if fill.side == "BUY":
            account.apply_buy_fill(pf)

    # Build market prices from latest candles
    market_prices: dict[str, Decimal] = {}
    latest_candles: dict[str, Candle] = {}
    for symbol in symbols:
        latest = candles_repo.get_latest(symbol, "15m")
        if latest is not None:
            market_prices[symbol] = Decimal(str(latest.close))
            latest_candles[symbol] = latest

    # Determine data freshness: fresh if latest 15m candle is within 30 minutes
    _STALE_THRESHOLD_SECONDS = 1800  # 30 min for 15m candles
    latest_ts = next((c.open_time for c in latest_candles.values()), None)
    data_is_fresh = (
        latest_ts is not None
        and (now - latest_ts).total_seconds() < _STALE_THRESHOLD_SECONDS
    )

    # Compute snapshot fields
    total_position_value = Decimal("0")
    symbol_position_values: dict[str, Decimal] = {}
    for symbol, position in account.positions.items():
        mkt_price = market_prices.get(symbol, position.avg_entry_price)
        val = position.qty * mkt_price
        symbol_position_values[symbol] = val
        total_position_value += val

    total_equity = account.total_equity(market_prices)
    account_equity = max(total_equity, initial_cash_usdt)

    total_position_pct = (
        (total_position_value / account_equity * Decimal("100"))
        if account_equity > 0
        else Decimal("0")
    )

    # Count today's orders per symbol
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    recent_orders = exec_repo.list_recent_orders(limit=1000)
    orders_today = [o for o in recent_orders if o.created_at >= today_start]

    daily_order_count = len(orders_today)
    symbol_daily_trade_count_map: dict[str, int] = {}
    for o in orders_today:
        symbol_daily_trade_count_map[o.symbol] = symbol_daily_trade_count_map.get(o.symbol, 0) + 1

    # Compute consecutive losses: count recent losing fills where current price
    # is below the position's avg_entry_price (not the raw fill price).
    # If market_prices lacks a symbol we fall back to avg_entry_price (equal,
    # so break immediately — no loss to count without a live price).
    # If the position is closed (pos is None) we also skip it.
    all_fills = exec_repo.list_fills_chronological()
    recent_fills = all_fills[-10:] if len(all_fills) > 10 else all_fills
    consecutive_losses = 0
    for fill in reversed(recent_fills):
        pos = account.positions.get(fill.symbol)
        if pos is None:
            continue  # no open position — skip this fill
        current = market_prices.get(fill.symbol, pos.avg_entry_price)
        if current < pos.avg_entry_price:
            consecutive_losses += 1
        else:
            break

    day_start_equity = _get_or_create_day_baseline(session, now, account_equity)

    inputs: list[CycleInput] = []
    for symbol in symbols:
        sym_pos_value = symbol_position_values.get(symbol, Decimal("0"))
        sym_position_pct = (
            (sym_pos_value / account_equity * Decimal("100"))
            if account_equity > 0
            else Decimal("0")
        )

        inputs.append(
            CycleInput(
                symbol=symbol,
                now=now,
                day_start_equity=day_start_equity,
                account_equity=account_equity,
                market_prices=market_prices,
                total_position_pct=total_position_pct,
                symbol_position_pct=sym_position_pct,
                open_positions=len(account.positions),
                daily_order_count=daily_order_count,
                symbol_daily_trade_count=symbol_daily_trade_count_map.get(symbol, 0),
                consecutive_losses=consecutive_losses,
                data_is_fresh=data_is_fresh,
                kill_switch_enabled=False,
            )
        )

    return inputs


def run_once(
    session_factory: Callable[[], Session],
    ai_scorer: AIScorer,
    symbols: list[str] | None = None,
    initial_cash_usdt: Decimal = Decimal("500"),
    fee_bps: Decimal = DEFAULT_FEE_BPS,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    min_notional: Decimal = DEFAULT_MIN_NOTIONAL,
    notifier: Notifier | None = None,
) -> list[CycleResult]:
    """Run one paper trading cycle for all configured symbols.

    Returns a list of CycleResults, one per symbol.
    """
    if symbols is None:
        symbols = SYMBOLS

    executor = PaperExecutor(fee_bps=fee_bps, slippage_bps=slippage_bps)
    now = datetime.now(UTC)
    results: list[CycleResult] = []
    notify = notifier or LogNotifier()

    with session_factory() as session:
        events_repo = EventsRepository(session)
        exec_repo = ExecutionRecordsRepository(session)

        events_repo.record_event(
            event_type="loop_started",
            severity="info",
            component="runner",
            message=f"Paper trading loop started for {symbols}",
            context={"symbols": symbols, "mode": "paper_only"},
        )

        inputs = _build_cycle_inputs(session, symbols, now, initial_cash_usdt)

        for input_data in inputs:
            try:
                result = run_paper_cycle(
                    input_data=input_data,
                    events_repo=events_repo,
                    exec_repo=exec_repo,
                    executor=executor,
                    ai_scorer=ai_scorer,
                    session_factory=session_factory,
                    min_notional_usdt=min_notional,
                )
                results.append(result)
            except Exception as exc:
                logger.exception("Unhandled exception in cycle for %s", input_data.symbol)
                events_repo.record_event(
                    event_type="cycle_error",
                    severity="error",
                    component="runner",
                    message=f"Unexpected error in cycle for {input_data.symbol}: {exc}",
                    context={"symbol": input_data.symbol, "error": str(exc)},
                )
                notify.notify(
                    NotificationLevel.ERROR,
                    f"Cycle error: {input_data.symbol}",
                    str(exc),
                    NotificationContext(symbol=input_data.symbol, error=str(exc)),
                )
                results.append(
                    CycleResult(
                        symbol=input_data.symbol,
                        status="error",
                        candidate_present=False,
                        ai_decision=None,
                        risk_state=None,
                        order_executed=False,
                        reject_reasons=[f"cycle_error: {exc}"],
                        event_ids=[],
                    )
                )

        events_repo.record_event(
            event_type="loop_finished",
            severity="info",
            component="runner",
            message="Paper trading loop iteration finished",
            context={"cycles_run": len(results)},
        )

    return results


def run_loop(
    interval_seconds: int,
    session_factory: Callable[[], Session],
    ai_scorer: AIScorer,
    max_cycles: int | None = None,
    stop_event: ThreadingEvent | None = None,
    symbols: list[str] | None = None,
    initial_cash_usdt: Decimal = Decimal("500"),
    fee_bps: Decimal = DEFAULT_FEE_BPS,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    min_notional: Decimal = DEFAULT_MIN_NOTIONAL,
    notifier: Notifier | None = None,
) -> int:
    """Run paper trading cycles on a fixed interval.

    Args:
        interval_seconds: seconds between each cycle run.
        session_factory: SQLAlchemy session factory.
        ai_scorer: AI scoring client.
        max_cycles: optional maximum number of cycles before exiting.
        stop_event: optional threading.Event to signal early exit.
        symbols: list of symbols to trade (default: SYMBOLS from candle service).
        initial_cash_usdt: initial cash balance for paper trading.
        fee_bps: fee in basis points for paper execution.
        slippage_bps: slippage in basis points for paper execution.
        min_notional: minimum order notional in USDT.
        notifier: optional Notifier adapter for critical alerts; defaults to LogNotifier.

    Returns:
        The number of cycles that were executed.

    Raises:
        ValueError: if interval_seconds is less than 1.
    """
    if interval_seconds < 1:
        raise ValueError(f"interval_seconds must be >= 1, got {interval_seconds}")
    if symbols is None:
        symbols = SYMBOLS

    stop = stop_event or ThreadingEvent()
    cycles_run = 0
    notify = notifier or LogNotifier()

    with session_factory() as session:
        events_repo = EventsRepository(session)
        events_repo.record_event(
            event_type="runner_started",
            severity="info",
            component="runner",
            message=(
                f"Paper trading runner started "
                f"(interval={interval_seconds}s, max_cycles={max_cycles})"
            ),
            context={
                "interval_seconds": interval_seconds,
                "max_cycles": max_cycles,
                "symbols": symbols,
                "mode": "paper_only",
            },
        )

    logger.info(
        "Starting paper trading loop: interval=%ds, max_cycles=%s, symbols=%s",
        interval_seconds,
        max_cycles,
        symbols,
    )

    try:
        while not stop.is_set():
            if max_cycles is not None and cycles_run >= max_cycles:
                logger.info("max_cycles reached (%d), exiting loop", cycles_run)
                break

            logger.info("Running cycle %d", cycles_run + 1)
            try:
                cycle_results = run_once(
                    session_factory=session_factory,
                    ai_scorer=ai_scorer,
                    symbols=symbols,
                    initial_cash_usdt=initial_cash_usdt,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    min_notional=min_notional,
                    notifier=notify,
                )
                for result in cycle_results:
                    logger.info(
                        "  %s: status=%s candidate_present=%s order_executed=%s",
                        result.symbol,
                        result.status,
                        result.candidate_present,
                        result.order_executed,
                    )
            except Exception as exc:
                logger.exception("Cycle %d raised an unhandled exception", cycles_run + 1)
                with session_factory() as session:
                    EventsRepository(session).record_event(
                        event_type="cycle_error",
                        severity="error",
                        component="runner",
                        message=f"Loop cycle {cycles_run + 1} crashed: {exc}",
                        context={"cycle": cycles_run + 1, "error": str(exc)},
                    )
                notify.notify(
                    NotificationLevel.ERROR,
                    "Cycle crashed",
                    f"Cycle {cycles_run + 1} raised an unhandled exception: {exc}",
                    NotificationContext(error=str(exc), cycle=cycles_run + 1),
                )

            cycles_run += 1

            if stop.is_set():
                break

            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping loop")
        stop.set()

    with session_factory() as session:
        EventsRepository(session).record_event(
            event_type="runner_stopped",
            severity="info",
            component="runner",
            message="Paper trading runner stopped",
            context={"cycles_run": cycles_run},
        )

    logger.info("Paper trading loop stopped after %d cycles", cycles_run)
    return cycles_run


def create_runner_session_factory() -> Callable[[], Session]:
    """Create and initialize a SQLAlchemy session factory for the runner."""

    from trading.runtime.config import AppSettings

    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    return create_session_factory(engine)
