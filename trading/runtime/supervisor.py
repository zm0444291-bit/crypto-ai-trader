"""Unified local supervisor — runs ingestion loop and paper trading loop concurrently.

Usage:
    from trading.runtime.supervisor import run_supervisor
    run_supervisor(
        ingest_interval=300,
        trade_interval=300,
        session_factory=session_factory,
        ai_scorer=ai_scorer,
        symbols=["BTCUSDT"],
        max_cycles=None,
    )
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event as ThreadingEvent
from typing import TYPE_CHECKING

from trading.ai.scorer import AIScorer
from trading.market_data.ingestion_runner import ingest_loop
from trading.notifications.base import NotificationContext, NotificationLevel, Notifier
from trading.notifications.dedup import AlertDeduplicator
from trading.notifications.log_notifier import LogNotifier
from trading.runtime.runner import run_loop
from trading.storage.repositories import EventsRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

INGESTION_DEFAULT_INTERVAL = 300
TRADING_DEFAULT_INTERVAL = 300

# Heartbeat stale threshold: trigger "lost" alert if last heartbeat older than this
HEARTBEAT_STALE_THRESHOLD_SECONDS = 120  # 2 minutes
# Minimum time a heartbeat must be healthy before another "lost" alert can fire
# (avoids flapping when heartbeat is intermittent)
HEARTBEAT_RECOVERY_CONFIRM_SECONDS = 60  # 1 minute of confirmed heartbeat


def run_supervisor(
    session_factory: Callable[[], Session],
    ai_scorer: AIScorer,
    ingest_interval: int = INGESTION_DEFAULT_INTERVAL,
    trade_interval: int = TRADING_DEFAULT_INTERVAL,
    max_cycles: int | None = None,
    symbols: list[str] | None = None,
    initial_cash_usdt: Decimal = Decimal("500"),
    notifier: Notifier | None = None,
    deduplicator: AlertDeduplicator | None = None,
) -> None:
    """Run both the ingestion loop and the paper trading loop concurrently.

    A shared stop event is used to signal both loops to shut down.
    KeyboardInterrupt in the main thread sets the stop event and joins
    both threads cleanly.
    """
    if ingest_interval < 1:
        raise ValueError(f"ingest_interval must be >= 1, got {ingest_interval}")
    if trade_interval < 1:
        raise ValueError(f"trade_interval must be >= 1, got {trade_interval}")

    _start_time = datetime.now(UTC)
    stop = ThreadingEvent()
    notify = notifier or LogNotifier()
    dedup = deduplicator or AlertDeduplicator(window_seconds=300)

    ingest_thread: threading.Thread | None = None
    trade_thread: threading.Thread | None = None

    # Heartbeat stale monitoring state — protected by the dedicated monitor thread
    # heartbeat_stale_alerted: True once we've sent a "lost" alert and haven't confirmed recovery
    # last_confirmed_heartbeat: most recent heartbeat time we've confirmed as live
    heartbeat_stale_alerted = False
    last_confirmed_heartbeat: datetime | None = None

    def _emit_heartbeat() -> None:
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="supervisor_heartbeat",
                    severity="info",
                    component="supervisor",
                    message="Supervisor heartbeat",
                    context={
                        "ingest_thread_alive": ingest_thread.is_alive(),
                        "trading_thread_alive": trade_thread.is_alive(),
                        "uptime_seconds": int(
                            (datetime.now(UTC) - _start_time).total_seconds()
                        ),
                        "symbols": symbols,
                    },
                )
        except Exception:
            pass  # never let heartbeat crash

    def _heartbeat_target() -> None:
        _emit_heartbeat()  # immediate first heartbeat
        while not stop.wait(timeout=60):
            try:
                _emit_heartbeat()
            except Exception:
                pass  # never let heartbeat crash

    def _monitor_target() -> None:
        """Check heartbeat freshness and trigger stale/lost/recovered alerts."""
        nonlocal heartbeat_stale_alerted, last_confirmed_heartbeat

        # No initial sleep needed: the heartbeat thread emits the first heartbeat
        # synchronously (before this thread starts), so a heartbeat always exists
        # when monitoring begins. Monitoring only triggers alerts when it detects
        # a gap between heartbeats (i.e. after the first heartbeat has aged past
        # the stale threshold), so there's no risk of false alerts at startup.
        while not stop.wait(timeout=60):
            try:
                _check_heartbeat_stale()
            except Exception:
                pass  # never let monitoring crash

        # On shutdown record a "supervisor_monitor_stopped" event for audit
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="supervisor_monitor_stopped",
                    severity="info",
                    component="supervisor",
                    message="Supervisor health monitor stopped",
                    context={"uptime_seconds": (datetime.now(UTC) - _start_time).total_seconds()},
                )
        except Exception:
            pass

    def _check_heartbeat_stale() -> None:
        """Check if the latest supervisor_heartbeat is stale and send alerts accordingly."""
        nonlocal heartbeat_stale_alerted, last_confirmed_heartbeat

        now = datetime.now(UTC)
        stale_threshold = now - timedelta(seconds=HEARTBEAT_STALE_THRESHOLD_SECONDS)
        recovery_confirm_threshold = now - timedelta(seconds=HEARTBEAT_RECOVERY_CONFIRM_SECONDS)

        try:
            latest_heartbeat_time: datetime | None = None
            with session_factory() as session:
                events_repo = EventsRepository(session)
                latest_hb_event = events_repo.get_latest_event_by_type("supervisor_heartbeat")
                if latest_hb_event is not None:
                    latest_heartbeat_time = latest_hb_event.created_at
                    if latest_hb_event.created_at.tzinfo is None:
                        latest_heartbeat_time = latest_hb_event.created_at.replace(
                            tzinfo=UTC
                        )

            if latest_heartbeat_time is None:
                # No heartbeat ever recorded
                return

            if latest_heartbeat_time >= stale_threshold:
                # Heartbeat is fresh
                last_confirmed_heartbeat = latest_heartbeat_time

                if heartbeat_stale_alerted:
                    # We were in stale state — heartbeat recovered
                    heartbeat_stale_alerted = False
                    # Only send recovered notification if we've had enough consecutive
                    # healthy heartbeats to confirm stability
                    if last_confirmed_heartbeat is not None and \
                       last_confirmed_heartbeat >= recovery_confirm_threshold:
                        _send_recovered_notification()
                # else: fresh and already healthy, nothing to do
            else:
                # Heartbeat is stale (older than threshold)
                if not heartbeat_stale_alerted:
                    heartbeat_stale_alerted = True
                    _send_heartbeat_lost_alert(latest_heartbeat_time)
        except Exception:
            pass  # never let monitoring crash

    def _send_heartbeat_lost_alert(last_heartbeat_time: datetime) -> None:
        """Send a 'heartbeat lost' alert when the supervisor stops emitting heartbeats."""
        ago = (datetime.now(UTC) - last_heartbeat_time).total_seconds()
        # Dedup applies to heartbeat_lost alerts too (avoids spam if monitor wakes frequently)
        if not dedup.should_notify(
            event_type="heartbeat_lost",
            component="supervisor",
            symbol=None,
        ):
            return
        # Record the lost event to DB for audit (always, even if notification suppressed)
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="heartbeat_lost",
                    severity="critical",
                    component="supervisor",
                    message=f"Supervisor heartbeat lost — no heartbeat for {int(ago)}s",
                    context={
                        "last_heartbeat_time": last_heartbeat_time.isoformat(),
                        "seconds_since_last_heartbeat": int(ago),
                        "alert_type": "heartbeat_lost",
                    },
                )
        except Exception:
            pass
        ctx: NotificationContext = {
            "event_type": "heartbeat_lost",
            "component": "supervisor",
            "error": f"No heartbeat for {int(ago)}s (last: {last_heartbeat_time.isoformat()})",
        }
        notify.notify(
            NotificationLevel.CRITICAL,
            "Heartbeat lost",
            f"No heartbeat for {int(ago)}s — supervisor may be hung or crashed",
            ctx,
        )

    def _send_recovered_notification() -> None:
        """Send a 'heartbeat recovered' notification after stability is confirmed."""
        # Dedup recovered notifications to avoid spam
        if not dedup.should_notify(
            event_type="heartbeat_recovered",
            component="supervisor",
            symbol=None,
        ):
            return
        ctx: NotificationContext = {
            "event_type": "heartbeat_recovered",
            "component": "supervisor",
        }
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="heartbeat_recovered",
                    severity="info",
                    component="supervisor",
                    message="Supervisor heartbeat recovered — normal operation resumed",
                    context={"alert_type": "heartbeat_recovered"},
                )
        except Exception:
            pass
        notify.notify(
            NotificationLevel.INFO,
            "Heartbeat recovered",
            "Supervisor heartbeat resumed after outage — operation normal",
            ctx,
        )

    with session_factory() as session:
        events_repo = EventsRepository(session)
        events_repo.record_event(
            event_type="supervisor_started",
            severity="info",
            component="supervisor",
            message="Supervisor started — running ingestion and trading loops",
            context={
                "startup_timestamp_utc": _start_time.isoformat(),
                "process_mode": "supervisor",
                "ingest_interval": ingest_interval,
                "trade_interval": trade_interval,
                "max_cycles": max_cycles,
                "symbols": symbols,
            },
        )

    logger.info(
        "Starting supervisor: ingest_interval=%ds trade_interval=%ds max_cycles=%s symbols=%s",
        ingest_interval,
        trade_interval,
        max_cycles,
        symbols,
    )

    ingestion_exc: Exception | None = None
    trading_exc: Exception | None = None

    def _ingestion_target() -> None:
        nonlocal ingestion_exc
        try:
            ingest_loop(
                interval_seconds=ingest_interval,
                session_factory=session_factory,
                symbols=symbols,
                max_cycles=max_cycles,
                stop_event=stop,
            )
        except Exception as exc:
            ingestion_exc = exc
            logger.exception("Ingestion thread raised an exception")
            stop.set()  # signal the other loop to shut down
            _record_component_error("ingestion", exc)

    def _trading_target() -> None:
        nonlocal trading_exc
        try:
            run_loop(
                interval_seconds=trade_interval,
                session_factory=session_factory,
                ai_scorer=ai_scorer,
                symbols=symbols,
                initial_cash_usdt=initial_cash_usdt,
                max_cycles=max_cycles,
                stop_event=stop,
                notifier=notify,
            )
        except Exception as exc:
            trading_exc = exc
            logger.exception("Trading thread raised an exception")
            stop.set()  # signal the other loop to shut down
            _record_component_error("trading", exc)

    def _record_supervisor_stopped(
        ing_exc: Exception | None, trade_exc: Exception | None
    ) -> None:
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="supervisor_stopped",
                    severity="info",
                    component="supervisor",
                    message="Supervisor stopped",
                    context={
                        "uptime_seconds": (
                            datetime.now(UTC) - _start_time
                        ).total_seconds(),
                        "ingestion_exc": type(ing_exc).__name__ if ing_exc else None,
                        "trading_exc": type(trade_exc).__name__ if trade_exc else None,
                    },
                )
        except Exception:
            pass  # never let recording crash the final shutdown

    def _record_component_error(component: str, exc: Exception) -> None:
        event_type = "supervisor_component_error"
        # Always record to DB (audit completeness — never suppressed)
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type=event_type,
                    severity="error",
                    component="supervisor",
                    message=f"Supervisor {component} component raised: {exc}",
                    context={
                        "component": component,
                        "error": str(exc),
                        "type": type(exc).__name__,
                    },
                )
        except Exception as record_exc:
            logger.warning(
                "Failed to record supervisor_component_error for %s: %s",
                component,
                record_exc,
            )
        # Deduplicate notification delivery (DB event always written above)
        if dedup.should_notify(event_type=event_type, component=component, symbol=None):
            ctx: NotificationContext = {
                "event_type": event_type,
                "component": component,
                "error": str(exc),
            }
            notify.notify(
                NotificationLevel.ERROR,
                f"Supervisor {component} error",
                str(exc),
                ctx,
            )

    ingest_thread = threading.Thread(target=_ingestion_target, name="ingestion-loop")
    trade_thread = threading.Thread(target=_trading_target, name="trading-loop")

    ingest_thread.start()
    trade_thread.start()

    heartbeat_thread = threading.Thread(target=_heartbeat_target, name="heartbeat")
    heartbeat_thread.start()

    monitor_thread = threading.Thread(target=_monitor_target, name="health-monitor")
    monitor_thread.start()

    def _wait_for_workers_to_finish() -> None:
        """Block until both worker threads have fully exited."""
        while ingest_thread.is_alive() or trade_thread.is_alive():
            ingest_thread.join(timeout=1)
            trade_thread.join(timeout=1)
        heartbeat_thread.join(timeout=1)
        monitor_thread.join(timeout=1)

    # Wait for both threads to finish before recording supervisor_stopped.
    # In resident mode (no max_cycles) this blocks indefinitely until a
    # KeyboardInterrupt is raised or both loops exit on their own.
    try:
        while True:
            if stop.is_set():
                break
            if not ingest_thread.is_alive() and not trade_thread.is_alive():
                break
            # Re-join with a short timeout so we can re-check stop periodically.
            # This lets KeyboardInterrupt wake the main thread and set stop.
            ingest_thread.join(timeout=1)
            trade_thread.join(timeout=1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping supervisor")
        stop.set()
        _wait_for_workers_to_finish()
        _record_supervisor_stopped(ingestion_exc, trading_exc)
        logger.info("Supervisor stopped.")
        return

    # Important: even if we break due to stop being set after a worker crash,
    # wait until both workers are fully done before raising/recording stop.
    _wait_for_workers_to_finish()

    if ingestion_exc is not None and trading_exc is None:
        raise ingestion_exc  # noqa: TRY201
    if trading_exc is not None and ingestion_exc is None:
        raise trading_exc  # noqa: TRY201
    if ingestion_exc is not None and trading_exc is not None:
        raise RuntimeError(
            f"Both loops failed — ingestion: {ingestion_exc!r}, trading: {trading_exc!r}"
        ) from ingestion_exc

    _record_supervisor_stopped(ingestion_exc, trading_exc)
    logger.info("Supervisor stopped.")
