"""CLI entrypoint for the local paper trading runner.

Usage:
    python -m trading.runtime.cli --once
    python -m trading.runtime.cli --interval 60 --max-cycles 5
    python -m trading.runtime.cli --supervisor
    python -m trading.runtime.cli --supervisor --ingest-interval 300 --trade-interval 300
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from decimal import Decimal

from trading.ai.http_client import HttpAIScoringClient
from trading.ai.minimax_client import MiniMaxAIScoringClient
from trading.ai.scorer import AIScorer
from trading.runtime.runner import (
    create_runner_session_factory,
    run_loop,
    run_once,
)
from trading.runtime.supervisor import (
    INGESTION_DEFAULT_INTERVAL,
    TRADING_DEFAULT_INTERVAL,
    run_supervisor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _build_ai_scorer() -> AIScorer:
    backend = os.environ.get("AI_SCORING_BACKEND", "http").strip().lower()
    if backend == "minimax":
        return AIScorer(MiniMaxAIScoringClient())
    return AIScorer(HttpAIScoringClient())


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto AI Trader — paper trading runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Run one cycle and exit")
    group.add_argument(
        "--interval", type=int, metavar="SECONDS", help="Run on a fixed interval (seconds)"
    )
    group.add_argument(
        "--supervisor", action="store_true", help="Run ingestion and trading loops concurrently"
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of cycles before exiting (default: unlimited)",
    )
    parser.add_argument(
        "--initial-cash",
        type=lambda s: Decimal(s),
        default=Decimal("500"),
        metavar="USDT",
        help="Initial cash balance in USDT (default: 500)",
    )
    parser.add_argument(
        "--symbols",
        type=lambda s: [sym.strip() for sym in s.split(",")],
        default=None,
        metavar="BTCUSDT,ETHUSDT,SOLUSDT",
        help="Comma-separated symbols to trade (default: all configured)",
    )
    parser.add_argument(
        "--ingest-interval",
        type=int,
        default=INGESTION_DEFAULT_INTERVAL,
        metavar="SECONDS",
        help=f"Data ingestion interval in seconds (default: {INGESTION_DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--trade-interval",
        type=int,
        default=TRADING_DEFAULT_INTERVAL,
        metavar="SECONDS",
        help=f"Trading loop interval in seconds (default: {TRADING_DEFAULT_INTERVAL})",
    )
    args = parser.parse_args()

    session_factory = create_runner_session_factory()
    ai_scorer = _build_ai_scorer()

    if args.once:
        logger.info("Running one paper trading cycle...")
        results = run_once(
            session_factory=session_factory,
            ai_scorer=ai_scorer,
            symbols=args.symbols,
            initial_cash_usdt=args.initial_cash,
        )
        for r in results:
            logger.info(
                "  %s: status=%s candidate_present=%s order_executed=%s",
                r.symbol,
                r.status,
                r.candidate_present,
                r.order_executed,
            )
        logger.info("Cycle complete.")
    elif args.supervisor:
        logger.info(
            "Starting supervisor: ingest_interval=%ds trade_interval=%ds max_cycles=%s",
            args.ingest_interval,
            args.trade_interval,
            args.max_cycles,
        )
        try:
            run_supervisor(
                session_factory=session_factory,
                ai_scorer=ai_scorer,
                ingest_interval=args.ingest_interval,
                trade_interval=args.trade_interval,
                max_cycles=args.max_cycles,
                symbols=args.symbols,
                initial_cash_usdt=args.initial_cash,
            )
        except Exception as exc:
            logger.error("Supervisor exited with error: %s", exc)
            sys.exit(1)
        logger.info("Supervisor exited cleanly.")
    else:
        assert args.interval is not None
        logger.info(
            "Starting paper trading loop: interval=%ds, max_cycles=%s",
            args.interval,
            args.max_cycles,
        )
        cycles = run_loop(
            interval_seconds=args.interval,
            session_factory=session_factory,
            ai_scorer=ai_scorer,
            max_cycles=args.max_cycles,
            symbols=args.symbols,
            initial_cash_usdt=args.initial_cash,
        )
        logger.info("Loop stopped after %d cycles.", cycles)


if __name__ == "__main__":
    main()
