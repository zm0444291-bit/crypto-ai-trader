"""Runtime service for executing paper trading cycles locally."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event as ThreadingEvent

from sqlalchemy.orm import Session

from trading.ai.scorer import AIScorer
from trading.dashboard_api.ws_manager import broadcast_from_sync
from trading.execution.paper_executor import PaperExecutor
from trading.market_data.adapters.base import BidAskQuote, MarketDataAdapter
from trading.market_data.candle_service import SYMBOLS
from trading.notifications.base import NotificationContext, NotificationLevel, Notifier
from trading.notifications.dedup import AlertDeduplicator
from trading.notifications.log_notifier import LogNotifier
from trading.notifications.telegram_notifier import TelegramNotifier
from trading.portfolio.accounting import PortfolioAccount
from trading.risk.risk_monitor import RiskMonitor
from trading.runtime.paper_cycle import CycleInput, CycleResult, run_paper_cycle
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.models import Candle
from trading.storage.repositories import (
    CandlesRepository,
    EventsRepository,
    ExecutionRecordsRepository,
)
from trading.strategies.active.strategy_selector import StrategySelector
from trading.strategies.exits import ExitEngine, load_exit_rules_from_yaml

# Derive config directory relative to this file (project_root / config)
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

logger = logging.getLogger(__name__)

# Default paper executor config
DEFAULT_FEE_BPS = Decimal("10")
DEFAULT_SLIPPAGE_BPS = Decimal("0")
DEFAULT_MIN_NOTIONAL = Decimal("10")

# Data freshness threshold: a 15m candle is considered stale after this many seconds
STALE_THRESHOLD_SECONDS = 1800  # 30 minutes


# ── API Failure Degradation ───────────────────────────────────────────────────


class APIFailureDegradation:
    """Per-symbol API failure tracker with progressive freeze.

    Tracks market-data and order failures independently per symbol.
    After the configured number of consecutive failures the symbol is
    frozen for a cooldown period, during which it is skipped by the
    trading loop.

    Telegram alerts are sent on freeze events (deduplicated externally).
    """

    def __init__(
        self,
        market_data_freeze_threshold: int = 3,
        market_data_freeze_minutes: int = 30,
        order_failure_freeze_threshold: int = 3,
        order_failure_freeze_minutes: int = 60,
        telegram_notifier: TelegramNotifier | None = None,
    ) -> None:
        self._market_data_freeze_threshold = market_data_freeze_threshold
        self._market_data_freeze_minutes = market_data_freeze_minutes
        self._order_failure_freeze_threshold = order_failure_freeze_threshold
        self._order_failure_freeze_minutes = order_failure_freeze_minutes
        self._telegram: TelegramNotifier | None = telegram_notifier

        # Failure counters: symbol -> consecutive failure count
        self._market_data_failures: dict[str, int] = {}
        self._order_failures: dict[str, int] = {}

        # Freeze state: symbol -> UTC datetime when freeze expires
        self._market_data_frozen_until: dict[str, datetime] = {}
        self._order_frozen_until: dict[str, datetime] = {}

    # ── Market-data failure handling ─────────────────────────────────────────

    def handle_market_data_failure(
        self,
        symbol: str,
        now: datetime | None = None,
    ) -> str:
        """Record one market-data API failure for *symbol*.

        Returns one of:
          - "retry"  — failure recorded but symbol not yet frozen
          - "frozen" — freeze threshold reached; symbol now frozen
        """
        if now is None:
            now = datetime.now(UTC)

        count = self._market_data_failures.get(symbol, 0) + 1
        self._market_data_failures[symbol] = count

        if count >= self._market_data_freeze_threshold:
            freeze_minutes = self._market_data_freeze_minutes
            self._market_data_frozen_until[symbol] = now.replace(
                microsecond=0
            ) + timedelta(minutes=freeze_minutes)
            self._market_data_failures[symbol] = 0  # reset counter after freeze
            self._send_alert(
                level="WARNING",
                title=f"[API] {symbol} market-data frozen",
                message=(
                    f"Market-data failures reached {count} for {symbol}. "
                    f"Trading frozen for {freeze_minutes} min."
                ),
                context={"event_type": "market_data_freeze", "symbol": symbol},
            )
            return "frozen"

        return "retry"

    # ── Order failure handling ───────────────────────────────────────────────

    def handle_order_failure(
        self,
        symbol: str,
        is_rate_limited: bool = False,
        now: datetime | None = None,
    ) -> str:
        """Record one order API failure for *symbol*.

        Args:
            symbol: trading symbol
            is_rate_limited: True when the exchange signalled rate-limiting
            now: current UTC datetime (defaults to datetime.now(UTC))

        Returns one of:
          - "retry"  — rate-limited; caller should retry without incrementing
          - "retry_counted" — non-rate-limit failure recorded, not yet frozen
          - "frozen" — freeze threshold reached; symbol now frozen
          - "abort"  — rate-limited failure should NOT be retried this cycle
        """
        if now is None:
            now = datetime.now(UTC)

        # Rate-limited failures never count against the freeze counter;
        # the caller is expected to back off and retry.
        if is_rate_limited:
            return "retry"  # caller backs off; no counter increment

        count = self._order_failures.get(symbol, 0) + 1
        self._order_failures[symbol] = count

        if count >= self._order_failure_freeze_threshold:
            freeze_minutes = self._order_failure_freeze_minutes
            self._order_frozen_until[symbol] = now.replace(
                microsecond=0
            ) + timedelta(minutes=freeze_minutes)
            self._order_failures[symbol] = 0  # reset counter after freeze
            self._send_alert(
                level="ERROR",
                title=f"[API] {symbol} order failures frozen",
                message=(
                    f"Order failures reached {count} for {symbol}. "
                    f"Trading frozen for {freeze_minutes} min."
                ),
                context={"event_type": "order_failure_freeze", "symbol": symbol},
            )
            return "frozen"

        return "retry_counted"

    # ── Freeze status ───────────────────────────────────────────────────────

    def is_symbol_frozen(self, symbol: str, now: datetime | None = None) -> bool:
        """Return True when *symbol* is currently in a freeze window."""
        if now is None:
            now = datetime.now(UTC)

        # Unfreeze if cooldown has elapsed
        mkt_until = self._market_data_frozen_until.get(symbol)
        if mkt_until is not None and now >= mkt_until:
            del self._market_data_frozen_until[symbol]
            mkt_until = None

        order_until = self._order_frozen_until.get(symbol)
        if order_until is not None and now >= order_until:
            del self._order_frozen_until[symbol]
            order_until = None

        return mkt_until is not None or order_until is not None

    def market_data_frozen_minutes_remaining(
        self, symbol: str, now: datetime | None = None
    ) -> int:
        """Seconds until market-data freeze expires (0 if not frozen)."""
        if now is None:
            now = datetime.now(UTC)
        until = self._market_data_frozen_until.get(symbol)
        if until is None or now >= until:
            return 0
        return int((until - now).total_seconds())

    def order_frozen_minutes_remaining(
        self, symbol: str, now: datetime | None = None
    ) -> int:
        """Seconds until order freeze expires (0 if not frozen)."""
        if now is None:
            now = datetime.now(UTC)
        until = self._order_frozen_until.get(symbol)
        if until is None or now >= until:
            return 0
        return int((until - now).total_seconds())

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _send_alert(
        self,
        level: str,
        title: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        """Send a Telegram alert if the notifier is configured."""
        if self._telegram is None:
            return
        try:
            from trading.notifications.base import NotificationContext, NotificationLevel

            notif_level = NotificationLevel(level.lower())
            ctx: NotificationContext = (context or {}).copy()  # type: ignore[assignment]
            self._telegram.notify(notif_level, title, message, ctx)
        except Exception:
            logger.exception("Failed to send freeze alert for %s", title)


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

    # Get the single most recent baseline event — no limit dependency
    event = events_repo.get_latest_event_by_type("day_baseline_set")
    if event is not None:
        ctx = event.context_json or {}
        if ctx.get("date") == str(today_utc):
            baseline_str = ctx.get("baseline")
            if baseline_str is not None:
                return Decimal(str(baseline_str))

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
    adapter: MarketDataAdapter | None = None,
) -> tuple[list[CycleInput], Decimal, Decimal]:
    """Build CycleInput for each symbol using live DB state.

    Returns:
        tuple of (inputs list, current account equity, day start equity).
    """

    exec_repo = ExecutionRecordsRepository(session)
    candles_repo = CandlesRepository(session)

    # Rebuild portfolio from historical fills
    account = PortfolioAccount(cash_balance=initial_cash_usdt)
    for fill in exec_repo.list_fills_chronological():

        from trading.execution.paper_executor import PaperFill

        pf = PaperFill(
            symbol=fill.symbol,
            side=fill.side,  # type: ignore[arg-type]
            price=fill.price,
            qty=fill.qty,
            fee_usdt=fill.fee_usdt,
            slippage_bps=fill.slippage_bps,
            filled_at=fill.filled_at,
        )
        if fill.side == "BUY":
            account.apply_buy_fill(pf)
        elif fill.side == "SELL":
            account.apply_sell_fill(pf)

    # Build market prices from latest candles
    market_prices: dict[str, Decimal] = {}
    latest_candles: dict[str, Candle] = {}
    for symbol in symbols:
        latest = candles_repo.get_latest(symbol, "15m")
        if latest is not None:
            market_prices[symbol] = Decimal(str(latest.close))
            latest_candles[symbol] = latest

    # Fetch real-time bid/ask quotes when adapter is available
    bid_ask_quotes: dict[str, BidAskQuote] | None = None
    if adapter is not None:
        bid_ask_quotes = {}
        for symbol in symbols:
            try:
                quote = adapter.get_bid_ask(symbol)
                bid_ask_quotes[symbol] = quote
            except Exception:
                pass  # Fall back to mid-price via market_prices when quote unavailable

    # Determine data freshness: fresh if latest 15m candle is within 30 minutes
    latest_ts = next((c.open_time for c in latest_candles.values()), None)
    if latest_ts is not None:
        # Normalize naive datetime to aware UTC before subtraction
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=UTC)
        data_is_fresh = (now - latest_ts).total_seconds() < STALE_THRESHOLD_SECONDS
    else:
        data_is_fresh = False

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
    # Preserve UTC timezone so comparison with timezone-aware created_at is valid
    today_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
                bid_ask_quotes=bid_ask_quotes,
                total_position_pct=total_position_pct,
                symbol_position_pct=sym_position_pct,
                open_positions=len(account.positions),
                daily_order_count=daily_order_count,
                symbol_daily_trade_count=symbol_daily_trade_count_map.get(symbol, 0),
                consecutive_losses=consecutive_losses,
                data_is_fresh=data_is_fresh,
                kill_switch_enabled=False,
                current_position=account.positions.get(symbol),
            )
        )

    return inputs, account_equity, day_start_equity


def run_once(
    session_factory: Callable[[], Session],
    ai_scorer: AIScorer,
    symbols: list[str] | None = None,
    initial_cash_usdt: Decimal = Decimal("500"),
    fee_bps: Decimal = DEFAULT_FEE_BPS,
    slippage_bps: Decimal = DEFAULT_SLIPPAGE_BPS,
    min_notional: Decimal = DEFAULT_MIN_NOTIONAL,
    notifier: Notifier | None = None,
    deduplicator: AlertDeduplicator | None = None,
    adapter: MarketDataAdapter | None = None,
) -> list[CycleResult]:
    """Run one paper trading cycle for all configured symbols.

    Returns a list of CycleResults, one per symbol.
    """
    if symbols is None:
        symbols = SYMBOLS

    executor = PaperExecutor(
        fee_bps=fee_bps,
        slippage_tiers={
            "default": slippage_bps,
            "XAUUSD": slippage_bps,
            "EURUSD": slippage_bps,
        },
    )
    exit_engine = ExitEngine(config=load_exit_rules_from_yaml(_CONFIG_DIR / "exit_rules.yaml"))
    now = datetime.now(UTC)
    results: list[CycleResult] = []
    notify = notifier or LogNotifier()
    dedup = deduplicator or AlertDeduplicator(window_seconds=300)
    # run_loop always passes a live instance; fallback for direct run_once callers

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

        inputs, account_equity, day_start_equity = _build_cycle_inputs(
            session, symbols, now, initial_cash_usdt, adapter=adapter
        )

        strategy_selector = StrategySelector(symbols=symbols)

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
                    exit_engine=exit_engine,
                    strategy_selector=strategy_selector,
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
                # Dedup: throttle repeat cycle_error notifications within 5-min window per symbol
                _dedup_key_ok = dedup.should_notify(
                    event_type="cycle_error",
                    component="runner",
                    symbol=input_data.symbol,
                )
                if _dedup_key_ok:
                    ctx: NotificationContext = {
                        "event_type": "cycle_error",
                        "component": "runner",
                        "symbol": input_data.symbol,
                        "error": str(exc),
                    }
                    notify.notify(
                        NotificationLevel.ERROR,
                        f"Cycle error: {input_data.symbol}",
                        str(exc),
                        ctx,
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

    # ── Risk monitoring ────────────────────────────────────────────────────
    # RiskMonitor evaluates equity drawdown and broadcasts risk_state_changed
    # events to the dashboard WS on transitions (normal → degraded → no_new_positions etc.)
    risk_monitor = RiskMonitor(day_start_equity=day_start_equity)
    risk_monitor.update_equity(account_equity)  # triggers evaluation + potential WS broadcast

    # Send Telegram alert when risk state transitions to degraded or worse.
    # Only notify on transition (not every cycle) to avoid spam.
    equity_alert = risk_monitor.check_equity_alert()
    if equity_alert is not None and dedup.should_notify(
        event_type="risk_state_change",
        component="risk_monitor",
        symbol=None,
    ):
        level_map = {
            "degraded": NotificationLevel.WARNING,
            "no_new_positions": NotificationLevel.ERROR,
            "global_pause": NotificationLevel.CRITICAL,
        }
        notify.notify(
            level_map.get(equity_alert.risk_state, NotificationLevel.WARNING),
            f"Risk alert: {equity_alert.risk_state}",
            equity_alert.message,
            {"risk_state": equity_alert.risk_state},
        )

    # ── WebSocket broadcast ────────────────────────────────────────────────
    # Dispatch summary to all connected dashboard clients.  We broadcast after
    # the session closes so this never blocks the DB transaction.
    if results:
        executed = [r for r in results if r.order_executed]
        broadcast_from_sync(
            "all",
            "cycle_complete",
            {
                "cycles_run": len(results),
                "executed_count": len(executed),
                "symbols": [r.symbol for r in results],
                "statuses": {r.symbol: r.status for r in results},
            },
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
    deduplicator: AlertDeduplicator | None = None,
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
        deduplicator: optional AlertDeduplicator for throttling repeat notifications.

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
    dedup = deduplicator or AlertDeduplicator(window_seconds=300)

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
                    deduplicator=dedup,
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
                # Dedup: throttle repeat cycle_error notifications within 5-min window
                # DB event is always recorded regardless of dedup decision.
                if dedup.should_notify(event_type="cycle_error", component="runner", symbol=None):
                    ctx: NotificationContext = {
                        "event_type": "cycle_error",
                        "component": "runner",
                        "error": str(exc),
                        "cycle": cycles_run + 1,
                    }
                    notify.notify(
                        NotificationLevel.ERROR,
                        "Cycle crashed",
                        f"Cycle {cycles_run + 1} raised an unhandled exception: {exc}",
                        ctx,
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
