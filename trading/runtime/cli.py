"""CLI entrypoint for the local paper trading runner.

Usage:
    python -m trading.runtime.cli --once
    python -m trading.runtime.cli --interval 60 --max-cycles 5
"""

from __future__ import annotations

import argparse
import logging
from decimal import Decimal

from trading.ai.scorer import AIScorer
from trading.runtime.runner import (
    create_runner_session_factory,
    run_loop,
    run_once,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class NoOpAIScorer:
    """Stub AI scorer that returns a fail-closed score.

    In production, replace with a real LLM-backed scorer.
    """

    def score(self, payload: dict) -> dict:
        logger.warning(
            "NoOpAIScorer is active — paper trading allows all candidates. "
            "Replace with a real AIScorer for production."
        )
        return {
            "ai_score": 75,
            "market_regime": "trend",
            "decision_hint": "allow",
            "risk_flags": [],
            "explanation": "No-op scorer: allow.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto AI Trader — paper trading runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Run one cycle and exit")
    group.add_argument(
        "--interval", type=int, metavar="SECONDS", help="Run on a fixed interval (seconds)"
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
    args = parser.parse_args()

    session_factory = create_runner_session_factory()
    ai_scorer: AIScorer = NoOpAIScorer()  # type: ignore[assignment]

    if args.once:
        logger.info("Running one paper trading cycle...")
        results = run_once(
            session_factory=session_factory,
            ai_scorer=ai_scorer,  # type: ignore[arg-type]
            symbols=args.symbols,
            initial_cash_usdt=args.initial_cash,
        )
        for r in results:
            logger.info(
                "  %s: status=%s candidate_present=%s order_executed=%s",
                r.status,
                r.candidate_present,
                r.order_executed,
            )
        logger.info("Cycle complete.")
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
            ai_scorer=ai_scorer,  # type: ignore[arg-type]
            max_cycles=args.max_cycles,
            symbols=args.symbols,
            initial_cash_usdt=args.initial_cash,
        )
        logger.info("Loop stopped after %d cycles.", cycles)


if __name__ == "__main__":
    main()
