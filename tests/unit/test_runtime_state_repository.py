"""Unit tests for RuntimeControlRepository."""


from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import RuntimeControlRepository


class TestRuntimeControlRepositoryDefaults:
    """Default values when the DB is empty."""

    def test_get_trade_mode_returns_default_when_empty(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/defaults.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            mode = repo.get_trade_mode()
            assert mode == "paper_auto"

    def test_get_live_trading_lock_returns_default_when_empty(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/defaults2.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            lock = repo.get_live_trading_lock()
            assert lock.enabled is False
            assert lock.reason is None


class TestRuntimeControlRepositoryModePersistence:
    """set/get trade mode persists correctly."""

    def test_set_and_get_mode_persists(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/mode.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paused")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            mode = repo.get_trade_mode()
            assert mode == "paused"

    def test_set_mode_overwrites_previous(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/mode_overwrite.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paper_auto")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("live_shadow")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            mode = repo.get_trade_mode()
            assert mode == "live_shadow"


class TestRuntimeControlRepositoryLockPersistence:
    """set/get live trading lock persists correctly."""

    def test_set_and_get_lock_persists(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/lock.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_live_trading_lock(enabled=True, reason="maintenance")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            lock = repo.get_live_trading_lock()
            assert lock.enabled is True
            assert lock.reason == "maintenance"

    def test_set_lock_without_reason(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/lock_no_reason.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_live_trading_lock(enabled=True)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            lock = repo.get_live_trading_lock()
            assert lock.enabled is True
            assert lock.reason is None

    def test_set_lock_disabled(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/lock_disabled.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_live_trading_lock(enabled=False)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            lock = repo.get_live_trading_lock()
            assert lock.enabled is False


class TestRuntimeControlRepositoryCrossSession:
    """Persistence across new session factory calls."""

    def test_mode_persists_across_sessions(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/cross_mode.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        repo = RuntimeControlRepository(session_factory())
        repo.set_trade_mode("live_shadow")

        new_session = session_factory()
        new_repo = RuntimeControlRepository(new_session)
        mode = new_repo.get_trade_mode()
        assert mode == "live_shadow"
        new_session.close()

    def test_lock_persists_across_sessions(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/cross_lock.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        repo = RuntimeControlRepository(session_factory())
        repo.set_live_trading_lock(enabled=True, reason="upgrade")
        repo.session.close()

        new_session = session_factory()
        new_repo = RuntimeControlRepository(new_session)
        lock = new_repo.get_live_trading_lock()
        assert lock.enabled is True
        assert lock.reason == "upgrade"
        new_session.close()


class TestRuntimeControlRepositorySnapshot:
    """get_control_plane_snapshot returns correct structure."""

    def test_snapshot_with_default_values(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/snapshot_defaults.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            snapshot = repo.get_control_plane_snapshot()
            assert snapshot["trade_mode"] == "paper_auto"
            assert snapshot["lock_enabled"] is False
            assert snapshot["lock_reason"] is None

    def test_snapshot_with_persisted_values(self, tmp_path):
        database_url = f"sqlite:///{tmp_path}/snapshot_persisted.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("live_shadow")
            repo.set_live_trading_lock(enabled=True, reason="maintenance")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            snapshot = repo.get_control_plane_snapshot()
            assert snapshot["trade_mode"] == "live_shadow"
            assert snapshot["lock_enabled"] is True
            assert snapshot["lock_reason"] == "maintenance"
