"""Integration tests for the runtime status dashboard API."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.dashboard_api import routes_runtime
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


class TestRuntimeStatusFailClosed:
    """API should fail-closed (never 500) when DB is unavailable."""

    def test_status_exception_fallback_is_fail_closed(self, monkeypatch):
        """When AppSettings or DB access throws, endpoint returns safe fail-closed values."""
        monkeypatch.setenv("DATABASE_URL", "/nonexistent/path/xxx.db")
        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_mode"] == "paper_auto"
        assert body["live_trading_lock_enabled"] is False
        assert body["execution_route_effective"] == "paper"
        assert body["mode_transition_guard"] == "blocked: unavailable"
        assert body["shadow_executions_last_hour"] == 0


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

    def test_runtime_status_does_not_write_reconciliation_events(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/status_readonly.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        client = TestClient(app)
        # Poll status multiple times like dashboard polling.
        assert client.get("/runtime/status").status_code == 200
        assert client.get("/runtime/status").status_code == 200

        with session_factory() as session:
            events_repo = EventsRepository(session)
            recon_events = events_repo.list_recent(
                limit=50,
                component="reconciliation",
            )

        # /runtime/status must remain read-only wrt event store.
        assert recon_events == []


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
        assert body["restart_attempts_ingestion_last_hour"] == 0
        assert body["restart_attempts_trading_last_hour"] == 0
        assert body["restart_exhausted_ingestion"] is False
        assert body["restart_exhausted_trading"] is False
        assert body["last_restart_time"] is None

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


class TestRuntimeStatusRestartObservability:
    """Restart-related observability fields are populated from supervisor events."""

    def test_restart_fields_populated_from_events(self, tmp_path, monkeypatch):
        database_url = f"sqlite:///{tmp_path}/restart_obs.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="component_restart_attempted",
                severity="info",
                component="supervisor",
                message="restart ingestion",
                context={"component": "ingestion", "attempt": 1, "reason": "boom"},
            )
            events_repo.record_event(
                event_type="component_restart_attempted",
                severity="info",
                component="supervisor",
                message="restart trading",
                context={"component": "trading", "attempt": 1, "reason": "boom"},
            )
            events_repo.record_event(
                event_type="component_restart_exhausted",
                severity="warning",
                component="supervisor",
                message="ingestion exhausted",
                context={"component": "ingestion", "attempt": 3, "reason": "max restarts"},
            )

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["restart_attempts_ingestion_last_hour"] >= 1
        assert body["restart_attempts_trading_last_hour"] >= 1
        assert body["restart_exhausted_ingestion"] is True
        assert body["restart_exhausted_trading"] is False
        assert body["last_restart_time"] is not None

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


class TestRuntimeStatusReconciliationField:
    """The reconciliation field is present and populated in /runtime/status responses."""

    def test_empty_db_returns_ok_reconciliation(self, tmp_path, monkeypatch):
        """Empty DB returns reconciliation with ok status and valid last_check_time.

        Reconciliation runs in the success path (DB is available via the tmp_path engine),
        so last_check_time is populated. The diff is OK because the mock interface
        balance (500 USDT) matches the initial cash (500 USDT).
        """
        database_url = f"sqlite:///{tmp_path}/recon_empty.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert "reconciliation" in body
        assert body["reconciliation"]["status"] == "ok"
        assert body["reconciliation"]["last_check_time"] is not None
        assert "balance_diff=" in body["reconciliation"]["diff_summary"]

    def test_fallback_reconciliation_on_db_init_failure(self, monkeypatch):
        """DB init failure returns reconciliation with ok status and unavailable diff_summary."""
        monkeypatch.setenv("DATABASE_URL", "/nonexistent/path/recon_init_fail.db")
        client = TestClient(app)
        response = client.get("/runtime/status")

        assert response.status_code == 200
        body = response.json()
        assert body["reconciliation"]["status"] == "ok"
        assert body["reconciliation"]["diff_summary"] == "unavailable"

    def test_runtime_status_is_read_only_for_reconciliation_events(self, tmp_path, monkeypatch):
        """Calling /runtime/status must not write reconciliation_* events."""
        database_url = f"sqlite:///{tmp_path}/recon_event.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        client = TestClient(app)

        # Call the status endpoint
        response = client.get("/runtime/status")
        assert response.status_code == 200

        # Check no reconciliation_* events were written by a read-only status call.
        with session_factory() as session:
            events_repo = EventsRepository(session)
            events = events_repo.list_recent(limit=10)
            recon_events = [e for e in events if e.event_type.startswith("reconciliation_")]
            assert recon_events == []


class TestControlPlaneWriteMode:
    """POST /runtime/control-plane/mode — safe, audited mode changes."""

    def test_legal_transition_paper_auto_to_live_shadow(self, tmp_path, monkeypatch):
        """paper_auto -> live_shadow is allowed and persists."""
        database_url = f"sqlite:///{tmp_path}/mode_cp1.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)

        # Start in paper_auto (default)
        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_shadow", "reason": "operator request"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["current_mode"] == "live_shadow"
        assert body["guard_reason"] == "transition_allowed"

    def test_illegal_transition_paused_to_live_small_auto(self, tmp_path, monkeypatch):
        """paused -> live_small_auto is blocked by validate_mode_transition."""
        database_url = f"sqlite:///{tmp_path}/mode_cp2.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-set mode to paused
        with session_factory() as session:
            RuntimeControlRepository(session).set_trade_mode("paused")

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_small_auto", "reason": "try live"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert "blocked" in body["guard_reason"]
        assert "live_small_auto" in body["guard_reason"]

    def test_paper_auto_to_live_small_auto_blocked_without_unlock(self, tmp_path, monkeypatch):
        """paper_auto -> live_small_auto requires allow_live_unlock=true."""
        database_url = f"sqlite:///{tmp_path}/mode_cp3.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_small_auto", "allow_live_unlock": False},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert "blocked" in body["guard_reason"]

    def test_same_mode_is_noop(self, tmp_path, monkeypatch):
        """Setting the same mode returns success without change."""
        database_url = f"sqlite:///{tmp_path}/mode_cp4.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            RuntimeControlRepository(session).set_trade_mode("paper_auto")

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "paper_auto"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["current_mode"] == "paper_auto"
        assert body["guard_reason"] == "same_mode"

    def test_mode_change_creates_audit_event(self, tmp_path, monkeypatch):
        """Successful mode change records a runtime_mode_changed event."""
        database_url = f"sqlite:///{tmp_path}/mode_cp5.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        client = TestClient(app)

        # legal transition: paper_auto -> live_shadow
        client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_shadow", "reason": "testing"},
        )

        # Verify event was recorded
        with session_factory() as session:
            events = EventsRepository(session).list_recent(limit=10)
            mode_events = [e for e in events if e.event_type == "runtime_mode_changed"]
            assert len(mode_events) == 1
            ctx = mode_events[0].context_json
            assert ctx["before_mode"] == "paper_auto"
            assert ctx["after_mode"] == "live_shadow"
            assert ctx["operator_source"] == "api"

    def test_mode_change_fail_closed_on_unavailable_db(self, monkeypatch):
        """When DB is unavailable, mode change returns fail-closed."""
        monkeypatch.setenv("DATABASE_URL", "/nonexistent/path/xxx.db")
        client = TestClient(app)

        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_shadow"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["guard_reason"] == "blocked: unavailable"
        assert body["current_mode"] == "paper_auto"

    def test_mode_change_exception_fallback_is_fail_closed(self, monkeypatch):
        """When session factory raises, mode change returns fail-closed (not 500)."""
        # Use a path that exists but with a locked file that causes session error
        monkeypatch.setenv("DATABASE_URL", "/tmp/fake_readonly_db.db")
        client = TestClient(app)

        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_shadow"},
        )

        # Must not return 500; must be fail-closed
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert "blocked" in body["guard_reason"]


class TestControlPlaneWriteLiveLock:
    """POST /runtime/control-plane/live-lock — safe, audited lock changes."""

    def test_enable_lock_succeeds(self, tmp_path, monkeypatch):
        """Enabling the live lock succeeds and persists."""
        database_url = f"sqlite:///{tmp_path}/lock_cp1.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)

        response = client.post(
            "/runtime/control-plane/live-lock",
            json={"enabled": True, "reason": "operator request"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["lock_enabled"] is True

    def test_disable_lock_succeeds(self, tmp_path, monkeypatch):
        """Disabling the live lock succeeds and persists."""
        database_url = f"sqlite:///{tmp_path}/lock_cp2.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-enable lock
        with session_factory() as session:
            RuntimeControlRepository(session).set_live_trading_lock(
                enabled=True, reason="initial"
            )

        client = TestClient(app)

        response = client.post(
            "/runtime/control-plane/live-lock",
            json={"enabled": False, "reason": "done"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["lock_enabled"] is False

    def test_lock_change_creates_audit_event(self, tmp_path, monkeypatch):
        """Successful lock change records a runtime_live_lock_changed event."""
        database_url = f"sqlite:///{tmp_path}/lock_cp3.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        client = TestClient(app)

        client.post(
            "/runtime/control-plane/live-lock",
            json={"enabled": True, "reason": "testing"},
        )

        with session_factory() as session:
            events = EventsRepository(session).list_recent(limit=10)
            lock_events = [
                e for e in events if e.event_type == "runtime_live_lock_changed"
            ]
            assert len(lock_events) == 1
            ctx = lock_events[0].context_json
            assert ctx["before_enabled"] is False
            assert ctx["after_enabled"] is True
            assert ctx["operator_source"] == "api"

    def test_lock_change_fail_closed_on_unavailable_db(self, monkeypatch):
        """When DB is unavailable, lock change returns fail-closed."""
        monkeypatch.setenv("DATABASE_URL", "/nonexistent/path/xxx.db")
        client = TestClient(app)

        response = client.post(
            "/runtime/control-plane/live-lock",
            json={"enabled": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["reason"] == "blocked: unavailable"


class TestControlPlaneWriteConsistency:
    """After a write, GET /runtime/status and /runtime/control-plane reflect the change."""

    def test_mode_write_visible_in_status_and_control_plane(self, tmp_path, monkeypatch):
        """After changing mode, both read endpoints reflect the new mode."""
        database_url = f"sqlite:///{tmp_path}/consist_cp1.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)

        # Change mode to live_shadow
        client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "live_shadow"},
        )

        # Check /runtime/status
        status_resp = client.get("/runtime/status")
        assert status_resp.json()["trade_mode"] == "live_shadow"
        assert status_resp.json()["execution_route_effective"] == "shadow"

        # Check /runtime/control-plane
        cp_resp = client.get("/runtime/control-plane")
        assert cp_resp.json()["trade_mode"] == "live_shadow"
        assert cp_resp.json()["execution_route"] == "shadow"

    def test_lock_write_visible_in_status_and_control_plane(self, tmp_path, monkeypatch):
        """After enabling lock, both read endpoints reflect lock_enabled=True."""
        database_url = f"sqlite:///{tmp_path}/consist_cp2.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)

        client = TestClient(app)

        # Enable lock
        client.post(
            "/runtime/control-plane/live-lock",
            json={"enabled": True, "reason": "testing"},
        )

        # Check /runtime/status
        status_resp = client.get("/runtime/status")
        assert status_resp.json()["live_trading_lock_enabled"] is True

        # Check /runtime/control-plane
        cp_resp = client.get("/runtime/control-plane")
        assert cp_resp.json()["lock_enabled"] is True


class TestLocalSystemExit:
    """POST /runtime/system/exit schedules local shutdown safely."""

    def test_exit_endpoint_schedules_shutdown(self, monkeypatch):
        client = TestClient(app)
        called = {"value": False}

        def _fake_schedule_local_shutdown(delay_seconds: float = 0.8) -> None:
            called["value"] = True

        monkeypatch.setattr(
            routes_runtime,
            "schedule_local_shutdown",
            _fake_schedule_local_shutdown,
        )

        response = client.post("/runtime/system/exit", json={"confirm": True})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["message"] == "shutdown_scheduled"
        assert called["value"] is True

    def test_exit_endpoint_requires_confirmation(self):
        client = TestClient(app)
        response = client.post("/runtime/system/exit", json={"confirm": False})
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["message"] == "blocked: confirmation_required"
