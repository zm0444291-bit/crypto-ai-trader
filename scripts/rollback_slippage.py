#!/usr/bin/env python3
"""Rollback slippage_bps in the fills table to canonical SLIPPAGE_TIERS.

This script is the counterpart to backfill_slippage.py. It reverts any
slippage_bps values that were written by the backfill script, restoring fills
to the canonical tier values defined in trading/execution/paper_executor.py.

Usage:
    python scripts/rollback_slippage.py          # dry-run (default)
    python scripts/rollback_slippage.py --execute # actually write to DB
    python scripts/rollback_slippage.py --help    # show this message

Idempotent: running twice yields the same result.
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path so we can import trading modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from trading.execution.paper_executor import SLIPPAGE_TIERS
from trading.storage.db import create_database_engine

LOG_FILE = PROJECT_ROOT / "logs" / "backfill_slippage.log"


def slippage_for_symbol(symbol: str, tiers: dict) -> Decimal:
    """Return the slippage tier (in bps) for a symbol, falling back to 'default'."""
    return tiers.get(symbol, tiers.get("default", Decimal("15")))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging to both file and stderr."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ],
    )


def describe_fills(engine) -> list[dict]:
    """Return all fills with their current slippage_bps and symbol."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, order_id, symbol, side, slippage_bps, filled_at FROM fills ORDER BY id")
        ).fetchall()
    return [
        {
            "id": r[0],
            "order_id": r[1],
            "symbol": r[2],
            "side": r[3],
            "slippage_bps": Decimal(str(r[4])),
            "filled_at": r[5],
        }
        for r in rows
    ]


def compute_rollbacks(fills: list[dict], canonical_tiers: dict) -> list[tuple]:
    """Return (fill_id, current, canonical, symbol) for fills that don't match canonical."""
    rollbacks = []
    for fill in fills:
        symbol = fill["symbol"]
        current = fill["slippage_bps"]
        canonical = slippage_for_symbol(symbol, canonical_tiers)
        if current != canonical:
            rollbacks.append((fill["id"], current, canonical, symbol))
    return rollbacks


def apply_rollbacks(engine, rollbacks: list[tuple], dry_run: bool = False) -> None:
    """Apply rollback of slippage_bps to canonical values."""
    if not rollbacks:
        logging.info("No rollbacks needed.")
        return

    with engine.connect() as conn:
        for fill_id, current_val, canonical_val, symbol in rollbacks:
            if dry_run:
                logging.info(
                    "[DRY-RUN] Would rollback fills.id=%d  symbol=%s  slippage_bps: %s -> %s (canonical)",
                    fill_id,
                    symbol,
                    current_val,
                    canonical_val,
                )
            else:
                conn.execute(
                    text("UPDATE fills SET slippage_bps = :val WHERE id = :id"),
                    {"val": str(canonical_val), "id": fill_id},
                )
                logging.info(
                    "Rolled back fills.id=%d  symbol=%s  slippage_bps: %s -> %s",
                    fill_id,
                    symbol,
                    current_val,
                    canonical_val,
                )
        if not dry_run:
            conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rollback fills.slippage_bps to canonical SLIPPAGE_TIERS from paper_executor.py."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write changes to the database. Without this flag only a dry-run is performed.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose (DEBUG) logging."
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    logging.info("=== rollback_slippage.py started [%s] ===", mode)

    canonical_tiers = SLIPPAGE_TIERS
    logging.info("Canonical SLIPPAGE_TIERS (from paper_executor.py): %s", canonical_tiers)

    database_url = "sqlite:///./data/crypto_ai_trader.sqlite3"
    engine = create_database_engine(database_url)
    logging.info("Connected to database: %s", database_url)

    fills = describe_fills(engine)
    total = len(fills)
    logging.info("Found %d fill record(s) in the database.", total)
    if total == 0:
        logging.info("Nothing to do.")
        return 0

    rollbacks = compute_rollbacks(fills, canonical_tiers)
    logging.info("Identified %d fill(s) needing rollback.", len(rollbacks))

    # Show current state
    logging.info("%-6s  %-12s  %-10s  %-12s  %-12s", "ID", "Symbol", "Side", "Current_bps", "Canonical_bps")
    logging.info("%-6s  %-12s  %-10s  %-12s  %-12s", "-" * 6, "-" * 12, "-" * 10, "-" * 12, "-" * 12)
    for fill in fills:
        canonical = slippage_for_symbol(fill["symbol"], canonical_tiers)
        marker = "  ***" if fill["slippage_bps"] != canonical else ""
        logging.info(
            "%-6s  %-12s  %-10s  %-12s  %-12s%s",
            fill["id"],
            fill["symbol"],
            fill["side"],
            fill["slippage_bps"],
            canonical,
            marker,
        )

    if not rollbacks:
        logging.info("All fill records already match canonical SLIPPAGE_TIERS.")
        return 0

    logging.info("")
    apply_rollbacks(engine, rollbacks, dry_run=not args.execute)
    logging.info("")

    if args.execute:
        logging.info("=== rollback_slippage.py completed [EXECUTE] — %d fill(s) rolled back ===", len(rollbacks))
    else:
        logging.info(
            "=== rollback_slippage.py completed [DRY-RUN] — run with --execute to apply %d rollback(s) ===",
            len(rollbacks),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
