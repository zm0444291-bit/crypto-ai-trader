"""Tests for P2: SQLite events table schema migration."""

import sqlite3

import pytest
from sqlalchemy import text

from trading.storage.db import (
    Base,
    create_database_engine,
    create_session_factory,
    init_db,
    migrate_sqlite_schema,
)
from trading.storage.repositories import EventsRepository


class TestEventsSchemaMigration:
    """P2: Old events table gets new columns via migrate_sqlite_schema."""

    def test_old_table_can_record_event_after_migration(self, tmp_path, monkeypatch):
        """Simulate a pre-migration events table (no new columns), migrate, then record.

        An old DB that was created before trace_id/cycle_id/etc. columns were added
        must be able to record_event with those fields after migration runs.
        Uses raw SQL to create an old-style events table without the new columns,
        bypassing Base.metadata which always creates the full schema.
        """
        db_path = tmp_path / "old_schema.sqlite3"
        database_url = f"sqlite:///{db_path}"

        # Create DB and events table WITHOUT new columns (pre-migration schema)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(80) NOT NULL,
                severity VARCHAR(20) NOT NULL,
                component VARCHAR(80) NOT NULL,
                message VARCHAR(500) NOT NULL,
                context_json TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)
        conn.execute("CREATE INDEX ix_events_event_type ON events(event_type)")
        conn.execute("CREATE INDEX ix_events_severity ON events(severity)")
        conn.execute("CREATE INDEX ix_events_component ON events(component)")
        conn.execute("CREATE INDEX ix_events_created_at ON events(created_at)")
        conn.commit()
        conn.close()

        # Verify the old schema is missing the new columns
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(events)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "trace_id" not in existing_cols
        assert "cycle_id" not in existing_cols
        assert "lifecycle_stage" not in existing_cols

        # Run migration
        monkeypatch.setenv("DATABASE_URL", database_url)
        engine = create_database_engine(database_url)
        migrate_sqlite_schema(engine)

        # Verify new columns exist after migration
        conn2 = sqlite3.connect(db_path)
        cursor2 = conn2.execute("PRAGMA table_info(events)")
        all_cols = {row[1] for row in cursor2.fetchall()}
        conn2.close()

        assert "trace_id" in all_cols
        assert "cycle_id" in all_cols
        assert "lifecycle_stage" in all_cols
        assert "symbol" in all_cols
        assert "side" in all_cols
        assert "mode" in all_cols
        assert "reason" in all_cols

        # Verify record_event works with the new fields
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            events_repo = EventsRepository(session)
            event = events_repo.record_event(
                event_type="test_migration",
                severity="info",
                component="test",
                message="Migration test event",
                trace_id="trace-123",
                cycle_id="cycle-456",
                symbol="BTCUSDT",
                side="BUY",
                mode="live_small_auto",
                lifecycle_stage="pre-flight",
                reason="test reason",
            )
            assert event.trace_id == "trace-123"
            assert event.cycle_id == "cycle-456"
            assert event.symbol == "BTCUSDT"
            assert event.side == "BUY"
            assert event.mode == "live_small_auto"
            assert event.lifecycle_stage == "pre-flight"
            assert event.reason == "test reason"

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        """Calling migrate_sqlite_schema twice must not raise or corrupt the schema."""
        database_url = f"sqlite:///{tmp_path}/idempotent.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        # Run migration first time
        migrate_sqlite_schema(engine)

        # Run migration second time — must not raise
        try:
            migrate_sqlite_schema(engine)
        except Exception as exc:
            pytest.fail(f"Second migration call raised: {exc}")

        # Verify all expected columns still exist
        conn = sqlite3.connect(tmp_path / "idempotent.sqlite3")
        cursor = conn.execute("PRAGMA table_info(events)")
        all_cols = {row[1] for row in cursor.fetchall()}
        conn.close()

        for col in ["trace_id", "cycle_id", "symbol", "lifecycle_stage"]:
            assert col in all_cols

    def test_migration_creates_indexes(self, tmp_path, monkeypatch):
        """Migration should create indexes on trace_id, cycle_id, symbol, lifecycle_stage."""
        database_url = f"sqlite:///{tmp_path}/indexed.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        migrate_sqlite_schema(engine)

        conn = sqlite3.connect(tmp_path / "indexed.sqlite3")
        cursor = conn.execute("PRAGMA index_list(events)")
        index_names = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "ix_events_trace_id" in index_names
        assert "ix_events_cycle_id" in index_names
        assert "ix_events_symbol" in index_names
        assert "ix_events_lifecycle_stage" in index_names

    def test_migration_skips_existing_indexes(self, tmp_path, monkeypatch):
        """Migration must not fail when indexes already exist (idempotent).

        Note: Base.metadata.create_all already creates indexes for columns with
        index=True, so indexes may already exist. Migration must handle this.
        """
        database_url = f"sqlite:///{tmp_path}/skip_existing.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        # Manually add another index on a column (side) that create_all didn't index
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX ix_events_side ON events(side)"))
            conn.commit()

        # Migration should skip all existing and not raise
        try:
            migrate_sqlite_schema(engine)
        except Exception as exc:
            pytest.fail(f"Migration failed on existing index: {exc}")

    def test_migration_only_runs_for_sqlite(self, tmp_path, monkeypatch):
        """Non-SQLite backends must skip migration silently.

        We test this by checking that no PostgreSQL-specific import or
        connection attempt is made — just the url check returns early.
        """
        # Mock the engine to avoid actual DB connection
        class FakeEngine:
            url = "postgresql://user:pass@localhost/test"

        # Should not raise — just return early
        migrate_sqlite_schema(FakeEngine())  # type: ignore[arg-type]

    def test_init_db_calls_migrate(self, tmp_path, monkeypatch):
        """init_db must call migrate_sqlite_schema automatically."""
        database_url = f"sqlite:///{tmp_path}/init_db_migrate.sqlite3"
        monkeypatch.setenv("DATABASE_URL", database_url)

        engine = create_database_engine(database_url)
        init_db(engine)

        # After init_db, new columns must exist
        conn = sqlite3.connect(tmp_path / "init_db_migrate.sqlite3")
        cursor = conn.execute("PRAGMA table_info(events)")
        all_cols = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "trace_id" in all_cols
        assert "lifecycle_stage" in all_cols