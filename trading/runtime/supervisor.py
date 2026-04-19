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
from decimal import Decimal
from threading import Event as ThreadingEvent
from typing import TYPE_CHECKING

from trading.ai.scorer import AIScorer
from trading.market_data.ingestion_runner import ingest_loop
from trading.notifications.base import NotificationContext, NotificationLevel, Notifier
from trading.notifications.log_notifier import LogNotifier
from trading.runtime.runner import run_loop
from trading.storage.repositories import EventsRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

INGESTION_DEFAULT_INTERVAL = 300
TRADING_DEFAULT_INTERVAL = 300


def run_supervisor(
    session_factory: Callable[[], Session],
    ai_scorer: AIScorer,
    ingest_interval: int = INGESTION_DEFAULT_INTERVAL,
    trade_interval: int = TRADING_DEFAULT_INTERVAL,
    max_cycles: int | None = None,
    symbols: list[str] | None = None,
    initial_cash_usdt: Decimal = Decimal("500"),
    notifier: Notifier | None = None,
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

    stop = ThreadingEvent()
    notify = notifier or LogNotifier()

    with session_factory() as session:
        events_repo = EventsRepository(session)
        events_repo.record_event(
            event_type="supervisor_started",
            severity="info",
            component="supervisor",
            message="Supervisor started — running ingestion and trading loops",
            context={
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
                        "ingestion_exc": type(ing_exc).__name__ if ing_exc else None,
                        "trading_exc": type(trade_exc).__name__ if trade_exc else None,
                    },
                )
        except Exception:
            pass  # never let recording crash the final shutdown

    def _record_component_error(component: str, exc: Exception) -> None:
        try:
            with session_factory() as session:
                EventsRepository(session).record_event(
                    event_type="supervisor_component_error",
                    severity="error",
                    component="supervisor",
                    message=f"Supervisor {component} component raised: {exc}",
                    context={
                        "component": component,
                        "error": str(exc),
                        "type": type(exc).__name__,
                    },
                )
            notify.notify(
                NotificationLevel.ERROR,
                f"Supervisor {component} error",
                str(exc),
                NotificationContext(error=str(exc)),
            )
        except Exception as record_exc:
            logger.warning(
                "Failed to record supervisor_component_error for %s: %s",
                component,
                record_exc,
            )

    ingest_thread = threading.Thread(target=_ingestion_target, name="ingestion-loop")
    trade_thread = threading.Thread(target=_trading_target, name="trading-loop")

    ingest_thread.start()
    trade_thread.start()

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
        ingest_thread.join(timeout=15)
        trade_thread.join(timeout=15)
        _record_supervisor_stopped(ingestion_exc, trading_exc)
        logger.info("Supervisor stopped.")
        return

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
