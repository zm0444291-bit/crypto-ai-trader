"""Integration tests for the runtime status dashboard API."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.models import Event
from trading.storage.repositories import EventsRepository, ExecutionRecordsRepository


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
