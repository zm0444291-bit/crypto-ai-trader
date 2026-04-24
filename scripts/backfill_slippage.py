#!/usr/bin/env python3
"""Backfill slippage_bps in the fills table based on SLIPPAGE_TIERS.

This script corrects historical fill records that may have been recorded with
incorrect slippage_bps values, bringing them in line with the current
SLIPPAGE_TIERS configuration in config/execution.yaml.

Usage:
    python scripts/backfill_slippage.py          # dry-run (default, shows what would change)
    python scripts/backfill_slippage.py --execute # actually write to DB
    python scripts/backfill_slippage.py --help    # show this message

The script is idempotent: running it twice in --execute mode produces the same
result as running it once. A backup of original values is logged before any
update.
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

import yaml

# Add project root to path so we can import trading modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text
from sqlalchemy.engine import Engine

from trading.execution.paper_executor import SLIPPAGE_TIERS
from trading.storage.db import create_database_engine

LOG_FILE = PROJECT_ROOT / "logs" / "backfill_slippage.log"


def load_execution_config() -> dict:
    """Load slippage_tiers from config/execution.yaml."""
    config_path = PROJECT_ROOT / "config" / "execution.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    tiers_raw: dict = cfg.get("slippage_tiers", {})
    # Convert all values to Decimal strings for consistency with SLIPPAGE_TIERS
    return {k: Decimal(str(v)) for k, v in tiers_raw.items()}


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


def describe_fills(engine: Engine) -> list[dict]:
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


def compute_updates(fills: list[dict], tiers: dict) -> list[tuple[int, Decimal, Decimal, str]]:
    """Compute (fill_id, old_slippage_bps, new_slippage_bps, symbol) for fills needing correction.

    Returns only fills where the current slippage_bps does NOT match the expected tier.
    """
    updates = []
    for fill in fills:
        symbol = fill["symbol"]
        current = fill["slippage_bps"]
        expected = slippage_for_symbol(symbol, tiers)
        if current != expected:
            updates.append((fill["id"], current, expected, symbol))
    return updates


def apply_updates(engine: Engine, updates: list[tuple], dry_run: bool = False) -> None:
    """Apply slippage_bps corrections to the fills table."""
    if not updates:
        logging.info("No updates needed.")
        return

    with engine.connect() as conn:
        for fill_id, old_val, new_val, symbol in updates:
            if dry_run:
                logging.info(
                    "[DRY-RUN] Would update fills.id=%d  symbol=%s  slippage_bps: %s -> %s",
                    fill_id,
                    symbol,
                    old_val,
                    new_val,
                )
            else:
                conn.execute(
                    text("UPDATE fills SET slippage_bps = :new_val WHERE id = :id"),
                    {"new_val": str(new_val), "id": fill_id},
                )
                logging.info(
                    "Updated fills.id=%d  symbol=%s  slippage_bps: %s -> %s",
                    fill_id,
                    symbol,
                    old_val,
                    new_val,
                )
        if not dry_run:
            conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill fills.slippage_bps based on SLIPPAGE_TIERS from config/execution.yaml."
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
    logging.info("=== backfill_slippage.py started [%s] ===", mode)

    # 1. Load tiers from config
    config_tiers = load_execution_config()
    logging.info("Loaded slippage_tiers from config/execution.yaml: %s", config_tiers)

    # 2. Canonical SLIPPAGE_TIERS from paper_executor (hard-coded reference values)
    canonical_tiers = SLIPPAGE_TIERS
    logging.info("Canonical SLIPPAGE_TIERS: %s", canonical_tiers)

    # 3. Warn if config and canonical differ
    for symbol in set(list(config_tiers.keys()) + list(canonical_tiers.keys())):
        cfg_val = config_tiers.get(symbol)
        canon_val = canonical_tiers.get(symbol)
        if cfg_val != canon_val:
            logging.warning(
                "Mismatch for %s: config=%s, canonical=%s — using config value.",
                symbol,
                cfg_val,
                canon_val,
            )

    # Use config values as the source of truth for this backfill
    tiers = config_tiers

    # 4. Load database engine
    database_url = "sqlite:///./data/crypto_ai_trader.sqlite3"
    engine = create_database_engine(database_url)
    logging.info("Connected to database: %s", database_url)

    # 5. Describe existing fills
    fills = describe_fills(engine)
    total = len(fills)
    logging.info("Found %d fill record(s) in the database.", total)
    if total == 0:
        logging.info("Nothing to do.")
        return 0

    # 6. Compute updates
    updates = compute_updates(fills, tiers)
    logging.info("Identified %d fill(s) needing correction.", len(updates))

    # 7. Show summary of all fills (current vs expected)
    logging.info("%-6s  %-12s  %-10s  %-12s  %-12s", "ID", "Symbol", "Side", "Current_bps", "Expected_bps")
    logging.info("%-6s  %-12s  %-10s  %-12s  %-12s", "-" * 6, "-" * 12, "-" * 10, "-" * 12, "-" * 12)
    for fill in fills:
        expected = slippage_for_symbol(fill["symbol"], tiers)
        marker = "  ***" if fill["slippage_bps"] != expected else ""
        logging.info(
            "%-6s  %-12s  %-10s  %-12s  %-12s%s",
            fill["id"],
            fill["symbol"],
            fill["side"],
            fill["slippage_bps"],
            expected,
            marker,
        )

    if not updates:
        logging.info("All fill records already have correct slippage_bps values.")
        return 0

    # 8. Apply (or preview) updates
    logging.info("")
    apply_updates(engine, updates, dry_run=not args.execute)
    logging.info("")

    if args.execute:
        logging.info("=== backfill_slippage.py completed [EXECUTE] — %d fill(s) updated ===", len(updates))
    else:
        logging.info(
            "=== backfill_slippage.py completed [DRY-RUN] — run with --execute to apply %d update(s) ===",
            len(updates),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
