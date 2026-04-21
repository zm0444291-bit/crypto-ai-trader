"""Migration script for Stage 2b: Data Migration + Schema Extension.

Creates 4 new DB tables (exit_signals, ai_scores, backtest_runs, strategy_params_history),
modifies risk_states with a new column, and supports dry-run, backup, and idempotent execution.

Usage:
    python scripts/migrate_stage2b.py [--dry-run] [--force]
    python scripts/migrate_stage2b.py --rollback  # undo the migration
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

_BACKUP_DIR = Path("data/backup_pre_2b")
_MIGRATION_LOCK_KEY = "stage2b_migration_completed_at"
_MIGRATION_VERSION = "2b"

# ── New table DDL ─────────────────────────────────────────────────────────────

_DDL_STATEMENTS: list[tuple[str, str]] = [
    # runtime_control (migration lock / key-value store)
    (
        "runtime_control",
        """
        CREATE TABLE IF NOT EXISTS runtime_control (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    # exit_signals
    (
        "exit_signals",
        """
        CREATE TABLE exit_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            signal_reason TEXT NOT NULL,
            qty_to_exit REAL NOT NULL CHECK (qty_to_exit > 0 AND qty_to_exit <= 1),
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            exit_price REAL,
            executed BOOLEAN NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(cycle_id, symbol, side)
        )
        """,
    ),
    # ai_scores
    (
        "ai_scores",
        """
        CREATE TABLE ai_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision_hint TEXT NOT NULL
                CHECK (decision_hint IN ('accept', 'reject', 'review')),
            ai_score REAL NOT NULL CHECK (ai_score >= 0 AND ai_score <= 1),
            model_used TEXT NOT NULL,
            reasoning TEXT,
            latency_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(cycle_id, symbol)
        )
        """,
    ),
    # backtest_runs
    (
        "backtest_runs",
        """
        CREATE TABLE backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            strategy_name TEXT NOT NULL,
            symbols TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            initial_equity_usdt REAL NOT NULL,
            final_equity_usdt REAL NOT NULL,
            total_return_pct REAL NOT NULL,
            sharpe_ratio REAL NOT NULL,
            max_drawdown_pct REAL NOT NULL,
            win_rate REAL NOT NULL,
            total_trades INTEGER NOT NULL,
            avg_win_loss_ratio REAL NOT NULL,
            monthly_returns_json TEXT NOT NULL DEFAULT '{}',
            equity_curve_json TEXT NOT NULL DEFAULT '[]',
            trades_json TEXT NOT NULL DEFAULT '[]',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    # strategy_params_history
    (
        "strategy_params_history",
        """
        CREATE TABLE strategy_params_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            param_key TEXT NOT NULL,
            param_value TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            reason TEXT,
            UNIQUE(strategy_name, param_key, changed_at)
        )
        """,
    ),
]

# risk_states: create table + add column (idempotent)
_RISK_STATES_DDL = """
CREATE TABLE IF NOT EXISTS risk_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    risk_state TEXT NOT NULL DEFAULT 'normal',
    day_start_equity_usdt REAL NOT NULL,
    current_equity_usdt REAL NOT NULL,
    daily_pnl_usdt REAL NOT NULL DEFAULT 0,
    daily_pnl_pct REAL NOT NULL DEFAULT 0,
    consecutive_losses_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_RISK_STATES_ADD_COLUMN = """
ALTER TABLE risk_states
ADD COLUMN consecutive_losses_json TEXT NOT NULL DEFAULT '{}'
"""


# ── Helper functions ───────────────────────────────────────────────────────────

def _get_db_path(database_url: str | None = None) -> Path:
    if database_url and database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    import os
    db_url = database_url or os.environ.get("DATABASE_URL", "")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///"))
    # Default: resolve relative to THIS script's directory (not CWD)
    return Path(__file__).resolve().parent.parent / "data" / "crypto_ai_trader.sqlite3"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def _acquire_lock(conn: sqlite3.Connection) -> bool:
    """Try to acquire a migration lock. Returns False if already locked."""
    try:
        conn.execute(
            "INSERT OR IGNORE INTO runtime_control (key, value_json, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            (_MIGRATION_LOCK_KEY, json.dumps({"version": _MIGRATION_VERSION, "locked": True})),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT value_json FROM runtime_control WHERE key=?", (_MIGRATION_LOCK_KEY,)
        )
        row = cur.fetchone()
        if row:
            val = json.loads(row[0])
            if val.get("locked"):
                return False
        return True
    except Exception:
        return False


def _release_lock(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "UPDATE runtime_control SET value_json=? WHERE key=?",
            (json.dumps({"version": _MIGRATION_VERSION, "locked": False}), _MIGRATION_LOCK_KEY),
        )
        conn.commit()
    except Exception:
        pass


# ── Core migration logic ───────────────────────────────────────────────────────

def _run_migration(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """Execute all DDL statements. Returns list of actions taken."""
    actions: list[str] = []

    for table_name, ddl in _DDL_STATEMENTS:
        if _table_exists(conn, table_name):
            actions.append(f"SKIP (already exists): {table_name}")
        else:
            if not dry_run:
                conn.execute(ddl)
                conn.commit()
            actions.append(f"CREATE: {table_name}")

    # risk_states: create table if not exists
    if not _table_exists(conn, "risk_states"):
        if not dry_run:
            conn.execute(_RISK_STATES_DDL)
            conn.commit()
        actions.append("CREATE: risk_states")
    else:
        actions.append("SKIP (already exists): risk_states")

    # Add consecutive_losses_json column if not exists
    if not _column_exists(conn, "risk_states", "consecutive_losses_json"):
        if not dry_run:
            conn.execute(_RISK_STATES_ADD_COLUMN)
            conn.commit()
        actions.append("ADD COLUMN: risk_states.consecutive_losses_json")
    else:
        actions.append("SKIP (column exists): risk_states.consecutive_losses_json")

    return actions


def _rollback_migration(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """Drop all Stage 2b tables and revert risk_states changes."""
    actions: list[str] = []
    tables_to_drop = [
        "exit_signals", "ai_scores", "backtest_runs", "strategy_params_history"
    ]
    for table in tables_to_drop:
        if _table_exists(conn, table):
            if not dry_run:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
            actions.append(f"DROP: {table}")
        else:
            actions.append(f"SKIP (not found): {table}")

    # SQLite does not support DROP COLUMN
    if _column_exists(conn, "risk_states", "consecutive_losses_json"):
        actions.append(
            "NOTE: SQLite does not support DROP COLUMN; "
            "risk_states.consecutive_losses_json remains"
        )

    return actions


def _validate_schema(conn: sqlite3.Connection) -> list[str]:
    """Validate that all expected tables/columns exist after migration."""
    errors: list[str] = []
    required = [
        "exit_signals", "ai_scores", "backtest_runs",
        "strategy_params_history", "risk_states",
    ]
    for table in required:
        if not _table_exists(conn, table):
            errors.append(f"MISSING table: {table}")

    if not _column_exists(conn, "risk_states", "consecutive_losses_json"):
        errors.append("MISSING column: risk_states.consecutive_losses_json")

    # Smoke-test insert into exit_signals
    try:
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('test', 'BTCUSDT', 'buy', 'test', 0.5, 0.9)"
        )
        conn.execute("DELETE FROM exit_signals WHERE cycle_id='test'")
    except Exception as e:
        errors.append(f"exit_signals insert failed: {e}")

    # Smoke-test insert into ai_scores
    try:
        conn.execute(
            "INSERT INTO ai_scores "
            "(cycle_id, symbol, decision_hint, ai_score, model_used) "
            "VALUES ('test2', 'ETHUSDT', 'accept', 0.5, 'test')"
        )
        conn.execute("DELETE FROM ai_scores WHERE cycle_id='test2'")
    except Exception as e:
        errors.append(f"ai_scores insert failed: {e}")

    return errors


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 2b DB migration script")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--force", action="store_true", help="Skip lock check and force migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback Stage 2b migration")
    parser.add_argument(
        "--validate", action="store_true", help="Validate schema after migration"
    )
    args = parser.parse_args()

    db_path = _get_db_path()
    if not db_path.exists():
        print(f"ERROR: Database file not found: {db_path}", file=sys.stderr)
        return 1

    # Backup before making changes
    if not args.dry_run and not args.rollback:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = _BACKUP_DIR / f"crypto_ai_trader_pre_2b_{ts}.sqlite3"
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, backup_path)
        print(f"[BACKUP] Created: {backup_path}")

    try:
        conn = _connect(db_path)

        # Lock check (skip in dry-run / force mode)
        if not args.dry_run and not args.force:
            if not _acquire_lock(conn):
                print(
                    "ERROR: Migration already in progress or previously completed.",
                    file=sys.stderr,
                )
                print("Use --force to override the lock.", file=sys.stderr)
                return 1

        try:
            if args.rollback:
                print("[ROLLBACK] Stage 2b migration...")
                actions = _rollback_migration(conn, dry_run=args.dry_run)
            else:
                print("[MIGRATION] Stage 2b...")
                actions = _run_migration(conn, dry_run=args.dry_run)

            for a in actions:
                mode = "[DRY-RUN]" if args.dry_run else "[APPLY]"
                print(f"  {mode} {a}")

            if not args.dry_run:
                if args.validate:
                    errors = _validate_schema(conn)
                    if errors:
                        print(f"[VALIDATION] FAILED: {errors}", file=sys.stderr)
                        return 1
                    print("[VALIDATION] PASSED")

                # Mark migration as completed
                conn.execute(
                    "INSERT OR REPLACE INTO runtime_control "
                    "(key, value_json, updated_at) "
                    "VALUES (?, ?, datetime('now'))",
                    (
                        _MIGRATION_LOCK_KEY,
                        json.dumps({
                            "version": _MIGRATION_VERSION,
                            "completed_at": datetime.now(UTC).isoformat(),
                            "locked": False,
                        }),
                    ),
                )
                conn.commit()
                print("[DONE] Stage 2b migration completed successfully.")
            else:
                print("[DRY-RUN] No changes applied.")

        finally:
            if not args.dry_run:
                _release_lock(conn)
            conn.close()

    except Exception:
        print("[ERROR] Migration failed:", file=sys.stderr)
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())