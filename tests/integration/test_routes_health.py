"""Integration tests for /health endpoint (routes_health.py)."""
"""Integration tests for /health endpoint (routes_health.py)."""
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.main import app
from trading.storage.db import Base
from trading.storage.models import Event


def _seed_events(session, events: list[dict]) -> None:
    for e in events:
        session.add(Event(**e))
    session.commit()


def _make_event(
    event_type: str,
    context: dict,
    created_at: datetime | None = None,
    severity: str = "info",
) -> dict:
    return {
        "event_type": event_type,
        "severity": severity,
        "component": "runtime",
        "message": "",
        "context_json": context,
        "created_at": created_at or datetime.now(UTC),
    }


# ─── /health endpoint structure ──────────────────────────────────────────────


def test_health_returns_ok_status():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "trade_mode" in body
    assert "live_trading_enabled" in body
    assert "risk_state" in body


def test_health_returns_all_required_fields():
    client = TestClient(app)
    response = client.get("/health")
    body = response.json()
    required = [
        "status",
        "trade_mode",
        "live_trading_enabled",
        "risk_state",
        "risk_profile_name",
        "daily_pnl_pct",
        "current_equity_usdt",
        "day_start_equity_usdt",
        "ingestion_heartbeat",
        "trading_heartbeat",
        "alert_messages",
        "stale_warning",
    ]
    for field in required:
        assert field in body, f"Missing field: {field}"


def test_health_daily_pnl_is_zero_when_no_baseline_event():
    client = TestClient(app)
    response = client.get("/health")
    body = response.json()
    assert body["daily_pnl_pct"] == "0" or body["daily_pnl_pct"] == 0


# ─── risk_state from DB ──────────────────────────────────────────────────────


def test_health_returns_unknown_when_no_risk_event():
    client = TestClient(app)
    response = client.get("/health")
    body = response.json()
    assert body["risk_state"] == "unknown"


def test_health_returns_risk_state_from_db():
    # Use a temp file DB so TestClient (separate thread) sees the same data
    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(db_fd)
    db_url = f"sqlite:///{db_path}"
    try:
        from trading.storage.db import create_database_engine, create_session_factory

        engine = create_database_engine(db_url)
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)

        now = datetime.now(UTC)
        _seed_events(
            factory(),
            [
                _make_event(
                    "risk_state_changed",
                    {"new_state": "degraded", "profile": "small_balanced"},
                    created_at=now,
                ),
            ],
        )

        import trading.dashboard_api.routes_health as rh_mod

        orig_latest = rh_mod._latest_event

        def _seeded_latest(event_type: str) -> dict[str, object]:
            from trading.storage.repositories import EventsRepository

            with factory() as session:
                repo = EventsRepository(session)
                evt = repo.get_latest_event_by_type(event_type)
                if evt is None:
                    return {"created_at": None, "context": {}}
                return {
                    "created_at": (
                        evt.created_at.isoformat() if evt.created_at else None
                    ),
                    "context": (
                        dict(evt.context_json) if evt.context_json else {}
                    ),
                }

        rh_mod._latest_event = _seeded_latest  # type: ignore[assignment]

        try:
            client = TestClient(app)
            response = client.get("/health")
            body = response.json()
            assert body["risk_state"] == "degraded"
            assert body["risk_profile_name"] == "small_balanced"
        finally:
            rh_mod._latest_event = orig_latest  # type: ignore[assignment]
    finally:
        os.unlink(db_path)


# ─── equity / daily PnL from DB ──────────────────────────────────────────────


def test_health_calculates_daily_pnl_from_baseline_and_portfolio():
    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(db_fd)
    db_url = f"sqlite:///{db_path}"
    try:
        from trading.storage.db import create_database_engine, create_session_factory

        engine = create_database_engine(db_url)
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)

        now = datetime.now(UTC)
        _seed_events(
            factory(),
            [
                _make_event(
                    "equity_baseline_set",
                    {"baseline": "1000.0"},
                    created_at=now,
                ),
                _make_event(
                    "portfolio_update",
                    {"total_equity": "950.0"},
                    created_at=now,
                ),
            ],
        )

        import trading.dashboard_api.routes_health as rh_mod

        orig_latest = rh_mod._latest_event

        def _seeded_latest(event_type: str) -> dict[str, object]:
            from trading.storage.repositories import EventsRepository

            with factory() as session:
                repo = EventsRepository(session)
                evt = repo.get_latest_event_by_type(event_type)
                if evt is None:
                    return {"created_at": None, "context": {}}
                return {
                    "created_at": (
                        evt.created_at.isoformat() if evt.created_at else None
                    ),
                    "context": (
                        dict(evt.context_json) if evt.context_json else {}
                    ),
                }

        rh_mod._latest_event = _seeded_latest  # type: ignore[assignment]

        try:
            client = TestClient(app)
            response = client.get("/health")
            body = response.json()
            assert Decimal(str(body["daily_pnl_pct"])) == Decimal("-5.0")
            assert Decimal(str(body["current_equity_usdt"])) == Decimal("950.0")
            assert Decimal(str(body["day_start_equity_usdt"])) == Decimal(
                "1000.0"
            )
        finally:
            rh_mod._latest_event = orig_latest  # type: ignore[assignment]
    finally:
        os.unlink(db_path)
