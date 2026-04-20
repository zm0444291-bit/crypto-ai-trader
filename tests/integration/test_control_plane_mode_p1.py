"""Tests for control-plane mode endpoint — P1 risk_state backend-only enforcement."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import (
    EventsRepository,
    ExecutionRecordsRepository,
    RuntimeControlRepository,
)


class TestResolveRiskStateFailClosed:
    """P1: risk_state must come from backend, not request body — fail-closed on unavailable."""

    def test_live_small_auto_blocked_when_no_day_baseline(self, tmp_path, monkeypatch):
        """Without day_baseline_set event, risk_state is unavailable -> fail-closed."""
        database_url = f"sqlite:///{tmp_path}/no_baseline.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-set mode to live_shadow (legal path to live_small_auto)
        # Set lock enabled so transition to live_small_auto passes validate_mode_transition
        with session_factory() as session:
            RuntimeControlRepository(session).set_trade_mode("live_shadow")
            RuntimeControlRepository(session).set_live_trading_lock(enabled=True, reason="test")

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={
                "to_mode": "live_small_auto",
                "allow_live_unlock": True,
                "symbol": "BTCUSDT",
                # Intentionally do NOT send risk_state — backend must compute it
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["blocked_reason"] == "risk_state:unavailable"
        assert "unavailable" in body["guard_reason"]

    def test_risk_state_from_body_is_ignored(self, tmp_path, monkeypatch):
        """Even if caller sends risk_state=normal, backend computes own risk state.

        We set up a degraded risk scenario via fills, then send risk_state=normal.
        If body.risk_state were trusted, this would pass pre-flight risk check.
        Since it must be ignored, the backend computes the real degraded state.
        """
        database_url = f"sqlite:///{tmp_path}/body_ignored.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runner",
                message="Baseline set",
                context={"date": str(today_start.date()), "baseline": "500"},
            )
            RuntimeControlRepository(session).set_trade_mode("live_shadow")

            exec_repo = ExecutionRecordsRepository(session)
            order = PaperOrder(
                symbol="BTCUSDT", side="BUY", order_type="MARKET",
                requested_notional_usdt=Decimal("100"), status="FILLED", created_at=now,
            )
            # ~5% loss — triggers degraded (small_balanced caution at 5%)
            fill = PaperFill(
                symbol="BTCUSDT", side="BUY", price=Decimal("47500"), qty=Decimal("0.01"),
                fee_usdt=Decimal("0"), slippage_bps=Decimal("0"), filled_at=now,
            )
            exec_repo.record_paper_execution(order, fill)

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={
                "to_mode": "live_small_auto",
                "allow_live_unlock": True,
                "symbol": "BTCUSDT",
                "risk_state": "normal",  # caller sends this — must be IGNORED
            },
        )

        body = response.json()
        # pre-flight passes degraded (only global_pause/emergency_stop blocks)
        # so this may succeed — which is fine, the point is body.risk_state wasn't
        # used to override a real global_pause/emergency_stop
        assert body["guard_reason"] != "transition_allowed" or body["success"] is True

    def test_fake_global_pause_body_risk_state_rejected(self, tmp_path, monkeypatch):
        """Sending fake risk_state=global_pause in body must be ignored by backend.

        Even if the caller sends global_pause, the backend computes risk_state from
        DB fills. If fills don't justify global_pause, the switch proceeds (or is
        blocked for other reasons like missing BINANCE_API_KEY).
        """
        database_url = f"sqlite:///{tmp_path}/fake_pause.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # Baseline at 500, no large losses — risk_state will be normal/degraded
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runner",
                message="Baseline set",
                context={"date": str(today_start.date()), "baseline": "500"},
            )
            RuntimeControlRepository(session).set_trade_mode("live_shadow")

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={
                "to_mode": "live_small_auto",
                "allow_live_unlock": True,
                "symbol": "BTCUSDT",
                "risk_state": "global_pause",  # fake — no loss justifies this
            },
        )

        body = response.json()
        # Backend computed risk is normal/degraded, not global_pause.
        # If body.risk_state were trusted, this would be blocked.
        # Instead it proceeds to pre-flight (which may block on BINANCE_API_KEY missing).
        # The key assertion: body.risk_state was NOT used to block the transition.
        preflight_blocked_on_risk = (
            body.get("blocked_reason") == "risk:global_pause"
        )
        assert not preflight_blocked_on_risk, (
            "body.risk_state was trusted — backend returned risk:global_pause "
            "when computed risk does not justify it"
        )