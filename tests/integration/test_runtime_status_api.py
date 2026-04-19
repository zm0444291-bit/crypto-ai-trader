"""Integration tests for the runtime status dashboard API."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.models import Event
from trading.storage.repositories import (
    EventsRepository,
    ExecutionRecordsRepository,
    RuntimeControlRepository,
    ShadowExecutionRepository,
)


class TestRuntimeStatusEmptyDB:
    """Empty DB should return safe defaults, not 500."""

    def test_empty_db_returns_null_defaults(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/empty.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        # Create client INSIDE test so monkeypatch has taken effect
        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["last_cycle_status"] is None
        assert body["last_cycle_time"] is None
        assert body["last_error_message"] is None
        assert body["cycles_last_hour"] == 0
        assert body["orders_last_hour"] == 0
        assert body["shadow_executions_last_hour"] == 0
        assert body["last_shadow_time"] is None
        # Guard must be fail-closed: never "transition_allowed" in fallback or empty-DB path
        assert body["mode_transition_guard"] != "transition_allowed"
        assert body["mode_transition_guard"] is not None
        assert body["mode_transition_guard"].startswith("blocked:")


class TestRuntimeStatusWithData:
    """DB with events and orders should produce correct counters and latest status."""

    def test_events_produce_cycles_last_hour_count(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/cycles.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # Two cycles in the last hour — recorded right now
            events_repo.record_event(
                event_type="cycle_started",
                severity="info",
                component="paper_cycle",
                message="Cycle 1",
                context={},
            )
            events_repo.record_event(
                event_type="cycle_started",
                severity="info",
                component="paper_cycle",
                message="Cycle 2",
                context={},
            )
            # One cycle older than 1 hour — insert directly to control created_at
            old_event = Event(
                event_type="cycle_started",
                severity="info",
                component="paper_cycle",
                message="Old cycle",
                context_json={},
                created_at=now - timedelta(hours=2),
            )
            session.add(old_event)
            session.commit()

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        assert response.json()["cycles_last_hour"] == 2

    def test_cycle_finished_provides_last_cycle_status_and_time(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/finished.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # Older cycle_finished — no_signal
            events_repo.record_event(
                event_type="cycle_finished",
                severity="info",
                component="paper_cycle",
                message="Old cycle",
                context={"status": "no_signal"},
            )
            # Most recent cycle_finished — executed
            events_repo.record_event(
                event_type="cycle_finished",
                severity="info",
                component="paper_cycle",
                message="Latest cycle",
                context={"status": "executed"},
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["last_cycle_status"] == "executed"
        assert body["last_cycle_time"] is not None

    def test_cycle_error_provides_last_error_message(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/error.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="cycle_error",
                severity="error",
                component="runner",
                message="Unexpected error in cycle for BTCUSDT: boom",
                context={"symbol": "BTCUSDT", "error": "boom"},
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["last_error_message"] is not None
        assert "BTCUSDT" in body["last_error_message"]
        assert "boom" in body["last_error_message"]

    def test_orders_produce_orders_last_hour_count(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/orders.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)
        recent = now - timedelta(minutes=30)

        with session_factory() as session:
            exec_repo = ExecutionRecordsRepository(session)
            for _ in range(2):
                order = PaperOrder(
                    symbol="BTCUSDT",
                    side="BUY",
                    order_type="MARKET",
                    requested_notional_usdt=Decimal("100"),
                    status="FILLED",
                    created_at=recent,
                )
                fill = PaperFill(
                    symbol="BTCUSDT",
                    side="BUY",
                    price=Decimal("50000"),
                    qty=Decimal("0.002"),
                    fee_usdt=Decimal("0.10"),
                    slippage_bps=Decimal("0"),
                    filled_at=recent,
                )
                exec_repo.record_paper_execution(order, fill)
            # One old order
            old_time = now - timedelta(hours=2)
            order_old = PaperOrder(
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                requested_notional_usdt=Decimal("100"),
                status="FILLED",
                created_at=old_time,
            )
            fill_old = PaperFill(
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("50000"),
                qty=Decimal("0.002"),
                fee_usdt=Decimal("0.10"),
                slippage_bps=Decimal("0"),
                filled_at=old_time,
            )
            exec_repo.record_paper_execution(order_old, fill_old)

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        assert response.json()["orders_last_hour"] == 2


class TestRuntimeStatusHeartbeatFields:
    """New heartbeat-supervision fields return safe defaults when no data is present."""

    def test_empty_db_returns_null_for_new_fields(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/empty.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["supervisor_alive"] is None
        assert body["ingestion_thread_alive"] is None
        assert body["trading_thread_alive"] is None
        assert body["uptime_seconds"] is None
        assert body["last_heartbeat_time"] is None
        assert body["last_component_error"] is None

    def test_heartbeat_produces_supervisor_alive_true(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/heartbeat.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="supervisor_heartbeat",
                severity="info",
                component="supervisor",
                message="Supervisor heartbeat",
                context={
                    "ingest_thread_alive": True,
                    "trading_thread_alive": True,
                    "uptime_seconds": 120,
                    "symbols": ["BTCUSDT"],
                },
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["supervisor_alive"] is True
        assert body["ingestion_thread_alive"] is True
        assert body["trading_thread_alive"] is True
        assert body["uptime_seconds"] == 120
        assert body["last_heartbeat_time"] is not None

    def test_stale_heartbeat_produces_supervisor_alive_false(self, tmp_path, monkeypatch):
        """Heartbeat older than 2 minutes is considered stale (supervisor alive = False)."""
        database_url = f"sqlite:///{tmp_path}/stale.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        stale_time = datetime.now(UTC) - timedelta(minutes=3)
        event = Event(
            event_type="supervisor_heartbeat",
            severity="info",
            component="supervisor",
            message="Stale heartbeat",
            context_json={
                "ingest_thread_alive": True,
                "trading_thread_alive": True,
                "uptime_seconds": 999,
                "symbols": [],
            },
            created_at=stale_time,
        )
        with session_factory() as session:
            session.add(event)
            session.commit()

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["supervisor_alive"] is False
        assert body["uptime_seconds"] == 999

    def test_component_error_sets_last_component_error(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/comperror.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # Older error first
            events_repo.record_event(
                event_type="supervisor_component_error",
                severity="error",
                component="supervisor",
                message="Old error",
                context={"component": "ingestion", "error": "old"},
            )
            # More recent error
            events_repo.record_event(
                event_type="supervisor_component_error",
                severity="error",
                component="supervisor",
                message="Ingestion thread crashed: network timeout",
                context={"component": "ingestion", "error": "network timeout"},
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["last_component_error"] == "Ingestion thread crashed: network timeout"


class TestRuntimeStatusWithControlPlane:
    """Status endpoint reflects persisted trade_mode and lock values."""

    def test_status_returns_persisted_trade_mode(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/control_mode.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-populate a trade mode
        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("live_shadow")

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "live_shadow"
        assert body["execution_route_effective"] == "shadow"

    def test_status_returns_persisted_lock_enabled(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/control_lock.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-populate a lock
        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_live_trading_lock(enabled=True, reason="maintenance")

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["live_trading_lock_enabled"] is True

    def test_defaults_when_db_empty(self, tmp_path, monkeypatch):
        """Empty DB should return safe defaults for control plane fields."""
        database_url = f"sqlite:///{tmp_path}/control_empty.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "paper_auto"
        assert body["live_trading_lock_enabled"] is False
        assert body["execution_route_effective"] == "paper"

    def test_mode_transition_guard_paper_auto(self, tmp_path, monkeypatch):
        """mode_transition_guard is present and reflects transition to live_small_auto."""
        database_url = f"sqlite:///{tmp_path}/guard.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        # paper_auto requires going through live_shadow first
        with create_session_factory(engine)() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paper_auto")

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["mode_transition_guard"] is not None
        assert "live_shadow" in body["mode_transition_guard"]

    def test_execution_route_reflects_trade_mode(self, tmp_path, monkeypatch):
        """execution_route_effective is correctly derived from trade_mode."""
        database_url = f"sqlite:///{tmp_path}/route.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        with create_session_factory(engine)() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("live_shadow")

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "live_shadow"
        assert body["execution_route_effective"] == "shadow"


class TestControlPlaneEndpoint:
    """GET /runtime/control-plane returns read-only snapshot."""

    def test_control_plane_returns_defaults_when_empty(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/cp_empty.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.get("/runtime/control-plane")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "paper_auto"
        assert body["lock_enabled"] is False
        assert body["lock_reason"] is None
        assert body["execution_route"] == "paper"
        # Guard must be fail-closed: never "transition_allowed" in empty-DB path
        assert body["transition_guard_to_live_small_auto"] != "transition_allowed"
        assert body["transition_guard_to_live_small_auto"].startswith("blocked:")

    def test_control_plane_returns_persisted_values(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/cp_persisted.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("live_shadow")
            repo.set_live_trading_lock(enabled=True, reason="upgrade")

        client = TestClient(app)
        response = client.get("/runtime/control-plane")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "live_shadow"
        assert body["lock_enabled"] is True
        assert body["lock_reason"] == "upgrade"
        assert body["execution_route"] == "shadow"

    def test_control_plane_exception_fallback_is_fail_closed(self, monkeypatch):
        """When AppSettings throws, fallback must be fail-closed (blocked: unavailable)."""
        monkeypatch.setenv("DATABASE_URL", "/nonexistent/path/xxx.db")
        client = TestClient(app)
        response = client.get("/runtime/control-plane")
        assert response.status_code == 200
        body = response.json()
        assert body["transition_guard_to_live_small_auto"] == "blocked: unavailable"


class TestRuntimeStatusShadowFields:
    """Shadow execution fields are correctly populated from the database."""

    def test_shadow_executions_last_hour_and_last_shadow_time(self, tmp_path, monkeypatch):
        """When shadow executions exist, endpoint returns correct count and latest time."""
        database_url = f"sqlite:///{tmp_path}/shadow.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            shadow_repo = ShadowExecutionRepository(session)
            # Two shadow executions in the last hour
            shadow_repo.record_shadow_execution(
                symbol="BTCUSDT",
                side="BUY",
                planned_notional_usdt=Decimal("100"),
                reference_price=Decimal("95000"),
                simulated_fill_price=Decimal("95010"),
                simulated_slippage_bps=Decimal("10"),
                decision_reason="test",
            )
            shadow_repo.record_shadow_execution(
                symbol="ETHUSDT",
                side="BUY",
                planned_notional_usdt=Decimal("50"),
                reference_price=Decimal("3500"),
                simulated_fill_price=Decimal("3503"),
                simulated_slippage_bps=Decimal("10"),
                decision_reason="test",
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["shadow_executions_last_hour"] == 2
        assert body["last_shadow_time"] is not None

    def test_shadow_defaults_when_no_shadow_executions(self, tmp_path, monkeypatch):
        """When no shadow executions exist, endpoint returns safe defaults."""
        database_url = f"sqlite:///{tmp_path}/no_shadow.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["shadow_executions_last_hour"] == 0
        assert body["last_shadow_time"] is None


