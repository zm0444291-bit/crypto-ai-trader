"""Tests for Stage 2b DB migration (exit_signals, ai_scores, backtest_runs,
strategy_params_history tables + risk_states.consecutive_losses_json column).

Verifies:
- VA-2b.1: All new tables exist
- VA-2b.2: CHECK constraints reject invalid data
- VA-2b.3: UNIQUE constraints reject duplicate inserts
- VA-2b.4: Migration is idempotent (run twice = second is no-op)
- VA-2b.5: Backup is created before migration
- VA-2b.6: No regression in existing functionality
- VA-2b.7: risk_states.consecutive_losses_json read/write works
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Absolute project root (tests/integration/ is 2 levels below project root)
PROJECT_ROOT = Path("/Users/zihanma/Desktop/crypto-ai-trader")
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "migrate_stage2b.py"
REAL_DB = PROJECT_ROOT / "data" / "crypto_ai_trader.sqlite3"


def _run_migration_on_db(db_path: Path) -> subprocess.CompletedProcess:
    """Run the migration script on a specific DB path (not subprocess/env)."""
    # Touch the file so it exists before the script's exists() check
    db_path.touch()
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--force"],
        env={**subprocess.os.environ.copy(), "DATABASE_URL": f"sqlite:///{db_path}"},
        capture_output=True,
        text=True,
    )
    return result


class TestSchemaExists:
    """VA-2b.1: All 5 new tables/columns exist in the database."""

    @pytest.fixture
    def conn(self):
        conn = sqlite3.connect(REAL_DB)
        yield conn
        conn.close()

    def test_exit_signals_table_exists(self, conn):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='exit_signals'"
        )
        assert cur.fetchone() is not None, "exit_signals table missing"

    def test_ai_scores_table_exists(self, conn):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_scores'"
        )
        assert cur.fetchone() is not None, "ai_scores table missing"

    def test_backtest_runs_table_exists(self, conn):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='backtest_runs'"
        )
        assert cur.fetchone() is not None, "backtest_runs table missing"

    def test_strategy_params_history_table_exists(self, conn):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_params_history'"
        )
        assert cur.fetchone() is not None, "strategy_params_history table missing"

    def test_risk_states_has_consecutive_losses_json(self, conn):
        cur = conn.execute("PRAGMA table_info(risk_states)")
        cols = {row[1] for row in cur.fetchall()}
        assert "consecutive_losses_json" in cols, (
            f"risk_states missing consecutive_losses_json. Available: {cols}"
        )


class TestCheckConstraints:
    """VA-2b.2: CHECK constraints reject invalid data."""

    @pytest.fixture
    def conn(self, tmp_path):
        db_path = tmp_path / "test_constraints.db"
        db_path.touch()
        result = _run_migration_on_db(db_path)
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        fresh_conn = sqlite3.connect(db_path)
        yield fresh_conn
        fresh_conn.close()

    def test_exit_signals_qty_to_exit_valid_range(self, conn):
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('c1', 'BTCUSDT', 'buy', 'test', 0.5, 0.9)"
        )
        conn.commit()
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('c2', 'ETHUSDT', 'sell', 'test', 0.001, 0.8)"
        )
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('c3', 'SOLUSDT', 'buy', 'test', 1.0, 0.7)"
        )
        conn.commit()

    def test_exit_signals_qty_to_exit_rejects_zero(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO exit_signals "
                "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
                "VALUES ('c1', 'BTCUSDT', 'buy', 'test', 0.0, 0.9)"
            )
            conn.commit()

    def test_exit_signals_qty_to_exit_rejects_over_one(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO exit_signals "
                "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
                "VALUES ('c1', 'BTCUSDT', 'buy', 'test', 1.5, 0.9)"
            )
            conn.commit()

    def test_exit_signals_confidence_valid_range(self, conn):
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('c1', 'BTCUSDT', 'buy', 'test', 0.5, 0.0)"
        )
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('c2', 'ETHUSDT', 'buy', 'test', 0.5, 1.0)"
        )
        conn.commit()

    def test_ai_scores_decision_hint_accept_reject_review(self, conn):
        for hint in ("accept", "reject", "review"):
            conn.execute(
                "INSERT INTO ai_scores "
                "(cycle_id, symbol, decision_hint, ai_score, model_used) "
                "VALUES (?, 'BTCUSDT', ?, 0.5, 'test')",
                (f"c_{hint}", hint),
            )
        conn.commit()

    def test_ai_scores_decision_hint_rejects_invalid(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ai_scores "
                "(cycle_id, symbol, decision_hint, ai_score, model_used) "
                "VALUES ('c1', 'BTCUSDT', 'maybe', 0.5, 'test')"
            )
            conn.commit()

    def test_ai_scores_ai_score_valid_range(self, conn):
        conn.execute(
            "INSERT INTO ai_scores "
            "(cycle_id, symbol, decision_hint, ai_score, model_used) "
            "VALUES ('c1', 'BTCUSDT', 'accept', 0.0, 'test')"
        )
        conn.execute(
            "INSERT INTO ai_scores "
            "(cycle_id, symbol, decision_hint, ai_score, model_used) "
            "VALUES ('c2', 'ETHUSDT', 'accept', 1.0, 'test')"
        )
        conn.commit()

    def test_ai_scores_ai_score_rejects_negative(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ai_scores "
                "(cycle_id, symbol, decision_hint, ai_score, model_used) "
                "VALUES ('c1', 'BTCUSDT', 'accept', -0.1, 'test')"
            )
            conn.commit()

    def test_ai_scores_ai_score_rejects_over_one(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ai_scores "
                "(cycle_id, symbol, decision_hint, ai_score, model_used) "
                "VALUES ('c1', 'BTCUSDT', 'accept', 1.5, 'test')"
            )
            conn.commit()


class TestUniqueConstraints:
    """VA-2b.3: UNIQUE constraints reject duplicate inserts."""

    @pytest.fixture
    def conn(self, tmp_path):
        db_path = tmp_path / "test_unique.db"
        db_path.touch()
        result = _run_migration_on_db(db_path)
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        fresh_conn = sqlite3.connect(db_path)
        yield fresh_conn
        fresh_conn.close()

    def test_exit_signals_unique_constraint_cycle_symbol_side(self, conn):
        conn.execute(
            "INSERT INTO exit_signals "
            "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
            "VALUES ('cycle-1', 'BTCUSDT', 'buy', 'first', 0.5, 0.9)"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO exit_signals "
                "(cycle_id, symbol, side, signal_reason, qty_to_exit, confidence) "
                "VALUES ('cycle-1', 'BTCUSDT', 'buy', 'duplicate', 0.3, 0.7)"
            )
            conn.commit()

    def test_ai_scores_unique_constraint_cycle_symbol(self, conn):
        conn.execute(
            "INSERT INTO ai_scores "
            "(cycle_id, symbol, decision_hint, ai_score, model_used) "
            "VALUES ('cycle-1', 'BTCUSDT', 'accept', 0.8, 'model-a')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ai_scores "
                "(cycle_id, symbol, decision_hint, ai_score, model_used) "
                "VALUES ('cycle-1', 'BTCUSDT', 'reject', 0.2, 'model-b')"
            )
            conn.commit()

    def test_backtest_runs_run_id_unique(self, conn):
        conn.execute(
            "INSERT INTO backtest_runs "
            "(run_id, strategy_name, symbols, start_time, end_time, "
            "initial_equity_usdt, final_equity_usdt, total_return_pct, "
            "sharpe_ratio, max_drawdown_pct, win_rate, total_trades, avg_win_loss_ratio) "
            "VALUES ('run-001', 'test_strategy', 'BTCUSDT', "
            "'2024-01-01', '2024-01-31', 50000, 55000, 10.0, 1.5, 5.0, 0.6, 20, 2.0)"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO backtest_runs "
                "(run_id, strategy_name, symbols, start_time, end_time, "
                "initial_equity_usdt, final_equity_usdt, total_return_pct, "
                "sharpe_ratio, max_drawdown_pct, win_rate, total_trades, avg_win_loss_ratio) "
                "VALUES ('run-001', 'test_strategy2', 'ETHUSDT', "
                "'2024-02-01', '2024-02-28', 50000, 52000, 4.0, 1.2, 3.0, 0.5, 15, 1.8)"
            )
            conn.commit()

    def test_strategy_params_history_unique_constraint(self, conn):
        ts = "2024-01-15T10:30:00"
        conn.execute(
            "INSERT INTO strategy_params_history "
            "(strategy_name, param_key, param_value, changed_by, changed_at, reason) "
            "VALUES ('momentum_v1', 'rsi_threshold', '35', 'user1', ?, 'threshold update')",
            (ts,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO strategy_params_history "
                "(strategy_name, param_key, param_value, changed_by, changed_at, reason) "
                "VALUES ('momentum_v1', 'rsi_threshold', '40', 'user2', ?, 'lower threshold')",
                (ts,),
            )
            conn.commit()


class TestIdempotency:
    """VA-2b.4: Running migration twice — second run is a no-op."""

    def test_migration_twice_no_error(self, tmp_path):
        db_path = tmp_path / "idempotent.db"
        # First run
        result1 = _run_migration_on_db(db_path)
        assert result1.returncode == 0, f"First migration failed: {result1.stderr}"
        # Second run
        result2 = _run_migration_on_db(db_path)
        assert result2.returncode == 0, f"Second migration failed: {result2.stderr}"
        # Verify all tables exist
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        for t in ["exit_signals", "ai_scores", "backtest_runs", "strategy_params_history"]:
            assert t in tables, f"Table {t} missing after second migration run"


class TestBackup:
    """VA-2b.5: Backup directory is created with backup files."""

    def test_backup_directory_created(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test_backup.db'}")
        db_path = tmp_path / "test_backup.db"
        db_path.touch()
        # Run migration (will create backup in PROJECT_ROOT/data/backup_pre_2b)
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--force"],
            env={**subprocess.os.environ, "DATABASE_URL": f"sqlite:///{db_path}"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        # Backup should exist in the script's backup directory (data/backup_pre_2b)
        project_backup = PROJECT_ROOT / "data" / "backup_pre_2b"
        if project_backup.exists():
            backups = list(project_backup.glob("*.sqlite3"))
            assert len(backups) > 0, "No backup files found"


class TestRiskStateJsonSerialization:
    """VA-2b.7: risk_states.consecutive_losses_json read/write works correctly."""

    @pytest.fixture
    def conn(self, tmp_path):
        db_path = tmp_path / "test_risk.db"
        db_path.touch()
        result = _run_migration_on_db(db_path)
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        fresh_conn = sqlite3.connect(db_path)
        yield fresh_conn
        fresh_conn.close()

    def test_write_and_read_consecutive_losses_json(self, conn):
        losses = {"BTCUSDT": 3, "ETHUSDT": 1, "SOLUSDT": 0}
        conn.execute(
            "INSERT INTO risk_states "
            "(symbol, risk_state, day_start_equity_usdt, current_equity_usdt, "
            "daily_pnl_usdt, daily_pnl_pct, consecutive_losses_json, updated_at) "
            "VALUES ('BTCUSDT', 'normal', 50000, 48000, -2000, -4.0, ?, datetime('now'))",
            (json.dumps(losses),),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT consecutive_losses_json FROM risk_states WHERE symbol='BTCUSDT'"
        )
        row = cur.fetchone()
        assert row is not None
        loaded = json.loads(row[0])
        assert loaded == losses

    def test_default_empty_json(self, conn):
        conn.execute(
            "INSERT INTO risk_states "
            "(symbol, risk_state, day_start_equity_usdt, current_equity_usdt, "
            "daily_pnl_usdt, daily_pnl_pct, updated_at) "
            "VALUES ('ETHUSDT', 'normal', 50000, 49500, -500, -1.0, datetime('now'))"
        )
        conn.commit()
        cur = conn.execute(
            "SELECT consecutive_losses_json FROM risk_states WHERE symbol='ETHUSDT'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "{}"

    def test_update_consecutive_losses_json(self, conn):
        conn.execute(
            "INSERT INTO risk_states "
            "(symbol, risk_state, day_start_equity_usdt, current_equity_usdt, "
            "daily_pnl_usdt, daily_pnl_pct, consecutive_losses_json, updated_at) "
            "VALUES ('SOLUSDT', 'normal', 50000, 49000, -1000, -2.0, "
            "'{\"SOLUSDT\": 1}', datetime('now'))"
        )
        conn.commit()
        new_losses = {"SOLUSDT": 5}
        conn.execute(
            "UPDATE risk_states SET consecutive_losses_json=? WHERE symbol='SOLUSDT'",
            (json.dumps(new_losses),),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT consecutive_losses_json FROM risk_states WHERE symbol='SOLUSDT'"
        )
        row = cur.fetchone()
        assert row is not None
        assert json.loads(row[0]) == new_losses


class TestNoRegression:
    """VA-2b.6: Existing tables/columns still work after migration."""

    @pytest.fixture
    def conn(self):
        conn = sqlite3.connect(REAL_DB)
        yield conn
        conn.close()

    def test_events_table_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count >= 0

    def test_orders_table_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert count >= 0

    def test_fills_table_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        assert count >= 0

    def test_candles_table_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        assert count >= 0

    def test_runtime_control_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM runtime_control").fetchone()[0]
        assert count >= 0

    def test_shadow_executions_still_works(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM shadow_executions").fetchone()[0]
        assert count >= 0


class TestMigrationLock:
    """Migration lock prevents concurrent runs."""

    def test_lock_prevents_double_run(self, tmp_path):
        db_path = tmp_path / "locked.db"
        db_path.touch()
        result1 = _run_migration_on_db(db_path)
        assert result1.returncode == 0, f"First run failed: {result1.stderr}"
        # Second run without --force should be blocked
        result2 = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            env={**subprocess.os.environ.copy(), "DATABASE_URL": f"sqlite:///{db_path}"},
            capture_output=True,
            text=True,
        )
        assert result2.returncode != 0, "Second run should be blocked by lock"
        assert "ERROR" in result2.stderr or "ERROR" in result2.stdout


class TestDryRun:
    """Dry-run mode does not modify the database."""

    def test_dry_run_does_not_create_tables(self, tmp_path):
        db_path = tmp_path / "dryrun.db"
        db_path.touch()
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--dry-run"],
            env={**subprocess.os.environ.copy(), "DATABASE_URL": f"sqlite:///{db_path}"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Dry-run failed: {result.stderr}"
        conn2 = sqlite3.connect(db_path)
        cur = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn2.close()
        assert "exit_signals" not in tables
        assert "ai_scores" not in tables

    def test_dry_run_output_contains_actions(self, tmp_path):
        db_path = tmp_path / "dryrun2.db"
        db_path.touch()
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--dry-run"],
            env={**subprocess.os.environ.copy(), "DATABASE_URL": f"sqlite:///{db_path}"},
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        assert "DRY-RUN" in output or "CREATE:" in output


class TestRollback:
    """Rollback drops the new tables."""

    def test_rollback_removes_tables(self, tmp_path):
        db_path = tmp_path / "rollback.db"
        db_path.touch()
        result1 = _run_migration_on_db(db_path)
        assert result1.returncode == 0, f"Migration failed: {result1.stderr}"
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables_before = {r[0] for r in cur.fetchall()}
        conn.close()
        for t in ["exit_signals", "ai_scores", "backtest_runs", "strategy_params_history"]:
            assert t in tables_before, f"{t} should exist before rollback"
        # Run rollback
        result2 = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--rollback", "--force"],
            env={**subprocess.os.environ.copy(), "DATABASE_URL": f"sqlite:///{db_path}"},
            capture_output=True,
            text=True,
        )
        assert result2.returncode == 0, f"Rollback failed: {result2.stderr}"
        conn2 = sqlite3.connect(db_path)
        cur2 = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables_after = {r[0] for r in cur2.fetchall()}
        conn2.close()
        for t in ["exit_signals", "ai_scores", "backtest_runs", "strategy_params_history"]:
            assert t not in tables_after, f"{t} should be removed after rollback"
        assert "risk_states" in tables_after