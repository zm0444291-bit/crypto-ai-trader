from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def sqlite_path_from_url(database_url: str) -> Path | None:
    """Return a local SQLite path for file-backed SQLite URLs."""

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None

    raw_path = database_url.removeprefix(prefix)
    if raw_path == ":memory:":
        return None

    return Path(raw_path)


def create_database_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine and ensure SQLite parent directories exist."""

    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(engine: Engine) -> None:
    """Create database tables and apply any pending schema migrations."""

    Base.metadata.create_all(engine)
    migrate_sqlite_schema(engine)


# Columns and indexes added to the events table after initial schema.
_EVENTS_NEW_COLUMNS: list[tuple[str, str]] = [
    ("trace_id", "TEXT"),
    ("cycle_id", "TEXT"),
    ("symbol", "TEXT"),
    ("side", "TEXT"),
    ("mode", "TEXT"),
    ("lifecycle_stage", "TEXT"),
    ("reason", "TEXT"),
]
_EVENTS_NEW_INDEXES: list[tuple[str, str]] = [
    ("ix_events_trace_id", "trace_id"),
    ("ix_events_cycle_id", "cycle_id"),
    ("ix_events_symbol", "symbol"),
    ("ix_events_lifecycle_stage", "lifecycle_stage"),
]


def migrate_sqlite_schema(engine: Engine) -> None:
    """Apply incremental schema migrations to an existing SQLite database.

    Safe to call on every init_db — uses IF NOT EXISTS / PRAGMA to make
    changes idempotent. Only runs for SQLite; other backends are skipped.
    Raises RuntimeError if a migration step fails.
    """
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return

    with engine.connect() as conn:
        # Helper: check if a column exists in a table
        def column_exists(table: str, col: str) -> bool:
            rows = conn.execute(
                text(f"PRAGMA table_info({table})"),
            ).fetchall()
            return any(r[1] == col for r in rows)

        # Helper: check if an index exists
        def index_exists(idx: str) -> bool:
            rows = conn.execute(
                text("PRAGMA index_list(events)"),
            ).fetchall()
            return any(r[1] == idx for r in rows)

        # Apply column additions
        for col_name, col_type in _EVENTS_NEW_COLUMNS:
            if not column_exists("events", col_name):
                try:
                    conn.execute(text(f"ALTER TABLE events ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception as exc:
                    raise RuntimeError(
                        f"migration failed: could not add column {col_name} to events"
                    ) from exc

        # Apply index creation
        for idx_name, col_name in _EVENTS_NEW_INDEXES:
            if not index_exists(idx_name):
                try:
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON events({col_name})"
                    ))
                    conn.commit()
                except Exception as exc:
                    raise RuntimeError(
                        f"migration failed: could not create index {idx_name} on events"
                    ) from exc


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional session scope."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
