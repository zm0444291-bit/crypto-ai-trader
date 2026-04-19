"""Market data ingestion runner — fetches public klines from Binance and persists them.

Usage:
    python -m trading.market_data.ingestion_runner --once
    python -m trading.market_data.ingestion_runner --interval 300
"""

from __future__ import annotations

import logging
from threading import Event as ThreadingEvent
from typing import TYPE_CHECKING

from trading.market_data.binance_client import BinanceKlineClient
from trading.market_data.candle_service import SYMBOLS, TIMEFRAMES
from trading.storage.repositories import CandlesRepository, EventsRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

INGESTION_DEFAULT_LIMIT = 100


def ingest_once(
    session: Session,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    limit: int = INGESTION_DEFAULT_LIMIT,
) -> dict[str, int]:
    """Fetch and upsert latest klines for all symbol/timeframe pairs.

    Returns a dict mapping each ``"symbol/timeframe"`` key to the number of
    candles inserted or updated.
    """
    if symbols is None:
        symbols = SYMBOLS
    if timeframes is None:
        timeframes = TIMEFRAMES

    client = BinanceKlineClient()
    candles_repo = CandlesRepository(session)
    events_repo = EventsRepository(session)
    counts: dict[str, int] = {}

    all_candles: list[tuple[str, str, int]] = []  # (symbol, timeframe, count)

    for symbol in symbols:
        for tf in timeframes:
            try:
                raw = client.fetch_klines(symbol, tf, limit=limit)
                affected = candles_repo.upsert_many(raw)
                counts[f"{symbol}/{tf}"] = affected
                all_candles.append((symbol, tf, affected))
            except Exception as exc:
                logger.warning("Failed to fetch %s %s: %s", symbol, tf, exc)
                counts[f"{symbol}/{tf}"] = 0

    total = sum(c for _, _, c in all_candles)
    symbols_ingested = [s for s, _, c in all_candles if c > 0]
    events_repo.record_event(
        event_type="data_ingested",
        severity="info",
        component="ingestion",
        message=f"Data ingestion completed: {total} candles for {symbols_ingested}",
        context={
            "total_candles": total,
            "symbols": symbols_ingested,
            "timeframes": timeframes,
        },
    )
    return counts


def ingest_loop(
    interval_seconds: int,
    session_factory: Callable[[], Session],
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    limit: int = INGESTION_DEFAULT_LIMIT,
    max_cycles: int | None = None,
    stop_event: ThreadingEvent | None = None,
) -> int:
    """Run ingest_once on a fixed interval.

    Returns the number of cycles executed.
    """
    if symbols is None:
        symbols = SYMBOLS
    if timeframes is None:
        timeframes = TIMEFRAMES

    stop = stop_event or ThreadingEvent()
    cycles_run = 0

    with session_factory() as session:
        EventsRepository(session).record_event(
            event_type="ingestion_runner_started",
            severity="info",
            component="ingestion",
            message=(
                f"Market data ingestion runner started "
                f"(interval={interval_seconds}s, max_cycles={max_cycles})"
            ),
            context={
                "interval_seconds": interval_seconds,
                "max_cycles": max_cycles,
                "symbols": symbols,
                "timeframes": timeframes,
            },
        )

    logger.info(
        "Starting market data ingestion loop: interval=%ds, max_cycles=%s, symbols=%s",
        interval_seconds,
        max_cycles,
        symbols,
    )

    try:
        while not stop.is_set():
            if max_cycles is not None and cycles_run >= max_cycles:
                logger.info("max_cycles reached (%d), exiting ingestion loop", cycles_run)
                break

            logger.info("Running ingestion cycle %d", cycles_run + 1)
            try:
                with session_factory() as session:
                    ingest_once(session, symbols, timeframes, limit)
            except Exception:
                logger.exception("Ingestion cycle %d raised an exception", cycles_run + 1)

            cycles_run += 1
            # stop.wait() returns immediately when stop is set, eliminating the
            # race window that existed between time.sleep() and the next check.
            stop.wait(timeout=interval_seconds)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping ingestion loop")

    with session_factory() as session:
        EventsRepository(session).record_event(
            event_type="ingestion_runner_stopped",
            severity="info",
            component="ingestion",
            message="Market data ingestion runner stopped",
            context={"cycles_run": cycles_run},
        )

    logger.info("Ingestion loop stopped after %d cycles", cycles_run)
    return cycles_run


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Market data ingestion runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Run one ingestion pass and exit")
    group.add_argument(
        "--interval", type=int, metavar="SECONDS", help="Run on a fixed interval (seconds)"
    )
    parser.add_argument(
        "--max-cycles", type=int, default=None, metavar="N", help="Maximum cycles before exiting"
    )
    args = parser.parse_args()

    from trading.runtime.config import AppSettings
    from trading.storage.db import create_database_engine, create_session_factory, init_db

    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    if args.once:
        with session_factory() as session:
            counts = ingest_once(session)
        for key, count in counts.items():
            print(f"  {key}: {count} candles")
        print("Ingestion complete.")
    else:
        assert args.interval is not None
        cycles = ingest_loop(
            interval_seconds=args.interval,
            session_factory=session_factory,
            max_cycles=args.max_cycles,
        )
        print(f"Ingestion loop stopped after {cycles} cycles.")
