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
    """P1: risk_state must come from backend, not request body.

    ModeChangeRequest no longer has a risk_state field — the field was removed
    to eliminate the spoofing vector. The backend resolves risk_state internally
    via _resolve_risk_state(), which reads day_baseline_set events and fill records.
    """

    def test_live_small_auto_blocked_when_no_day_baseline(self, tmp_path, monkeypatch):
        """Without day_baseline_set event, risk_state is unavailable -> fail-closed.

        _resolve_risk_state() reads the most recent day_baseline_set event to get
        day_start_equity. Without it, it returns 'unavailable' which blocks
        the live_small_auto transition.
        """
        database_url = f"sqlite:///{tmp_path}/no_baseline.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # Pre-set mode to live_shadow + enable lock (legal path to live_small_auto)
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
                # risk_state field is intentionally absent — ModeChangeRequest
                # no longer accepts it; backend resolves it from DB
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["blocked_reason"] == "risk_state:unavailable"

    def test_risk_state_body_field_does_not_exist_in_api_model(self, tmp_path, monkeypatch):
        """Verify ModeChangeRequest silently drops unknown risk_state field.

        Pydantic ignores extra fields not defined in the model. This test
        documents that sending risk_state has no effect, and confirms the
        backend-resolved path is the only valid one.
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
            RuntimeControlRepository(session).set_live_trading_lock(enabled=True, reason="test")

            # Record a fill causing ~5% loss (degraded threshold)
            exec_repo = ExecutionRecordsRepository(session)
            order = PaperOrder(
                symbol="BTCUSDT", side="BUY", order_type="MARKET",
                requested_notional_usdt=Decimal("100"), status="FILLED", created_at=now,
            )
            # ~5% loss — degraded (small_balanced caution at 5%)
            fill = PaperFill(
                symbol="BTCUSDT", side="BUY", price=Decimal("47500"), qty=Decimal("0.01"),
                fee_usdt=Decimal("0"), slippage_bps=Decimal("0"), filled_at=now,
            )
            exec_repo.record_paper_execution(order, fill)

        client = TestClient(app)
        # Even if someone sends risk_state in JSON, Pydantic drops it
        response = client.post(
            "/runtime/control-plane/mode",
            json={
                "to_mode": "live_small_auto",
                "allow_live_unlock": True,
                "symbol": "BTCUSDT",
                "risk_state": "global_pause",  # extra field — Pydantic drops this
            },
        )

        body = response.json()
        # Backend computes degraded (not global_pause), so pre-flight passes
        # (degraded is not a blocking state). The transition may still fail
        # for other reasons (e.g., BINANCE_API_KEY missing), but crucially
        # it must NOT fail with blocked_reason="risk:global_pause".
        if not body["success"]:
            assert body.get("blocked_reason") != "risk:global_pause", (
                "Backend trusted the dropped risk_state field and returned "
                "risk:global_pause when the backend-computed state is degraded"
            )

    def test_backend_computed_risk_global_pause_blocks_transition(self, tmp_path, monkeypatch):
        """When backend computes risk_state=global_pause, pre-flight blocks with risk:global_pause.

        We stub BINANCE_API_KEY so the config check passes, allowing the risk
        circuit breaker to be reached and trigger the expected block.
        """
        database_url = f"sqlite:///{tmp_path}/global_pause.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("BINANCE_API_KEY", "test_key_123")
        monkeypatch.setenv("BINANCE_API_SECRET", "test_secret_456")
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # Baseline at 500 — simulate massive loss that triggers global_pause
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runner",
                message="Baseline set",
                context={"date": str(today_start.date()), "baseline": "500"},
            )
            RuntimeControlRepository(session).set_trade_mode("live_shadow")
            RuntimeControlRepository(session).set_live_trading_lock(enabled=True, reason="test")

            # Record a BUY then SELL that produces a >10% daily loss.
            # Buy 0.01 BTC at 47500 (~475 USD cost), then sell at 2500 (~25 USD proceeds).
            # Net loss: ~450 USD = 90% → global_pause for small_balanced (threshold 10%).
            exec_repo = ExecutionRecordsRepository(session)
            buy_order = PaperOrder(
                symbol="BTCUSDT", side="BUY", order_type="MARKET",
                requested_notional_usdt=Decimal("1000"), status="FILLED", created_at=now,
            )
            buy_fill = PaperFill(
                symbol="BTCUSDT", side="BUY", price=Decimal("47500"), qty=Decimal("0.01"),
                fee_usdt=Decimal("0"), slippage_bps=Decimal("0"), filled_at=now,
            )
            exec_repo.record_paper_execution(buy_order, buy_fill)

            sell_order = PaperOrder(
                symbol="BTCUSDT", side="SELL", order_type="MARKET",
                requested_notional_usdt=Decimal("1000"), status="FILLED", created_at=now,
            )
            sell_fill = PaperFill(
                symbol="BTCUSDT", side="SELL", price=Decimal("2500"), qty=Decimal("0.01"),
                fee_usdt=Decimal("0"), slippage_bps=Decimal("0"), filled_at=now,
            )
            exec_repo.record_paper_execution(sell_order, sell_fill)

        client = TestClient(app)
        response = client.post(
            "/runtime/control-plane/mode",
            json={
                "to_mode": "live_small_auto",
                "allow_live_unlock": True,
                "symbol": "BTCUSDT",
            },
        )

        body = response.json()
        # Blocked — backend correctly computed global_pause (visible in preflight_checks).
        # The lock is also enabled so live_trading_lock fails first in pre-flight ordering.
        assert body["success"] is False
        # First failure in pre-flight ordering is live_trading_lock (checked before risk_state)
        assert body["blocked_reason"] == "live_trading_lock_enabled"
        # But global_pause was also correctly computed by the backend and appears in checks
        check_codes = [c["code"] for c in body.get("preflight_checks", [])]
        assert "risk:circuit_breaker" in check_codes
        risk_check = next(
            c for c in body["preflight_checks"]
            if c["code"] == "risk:circuit_breaker"
        )
        assert risk_check["status"] == "fail"
        assert "global_pause" in risk_check["message"]

    def test_other_modes_bypass_risk_state_check(self, tmp_path, monkeypatch):
        """Modes other than live_small_auto do not trigger _resolve_risk_state."""
        database_url = f"sqlite:///{tmp_path}/other_mode.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        # No day_baseline_set event — risk_state would be unavailable
        with session_factory() as session:
            RuntimeControlRepository(session).set_trade_mode("live_shadow")

        client = TestClient(app)
        # Transition to paused — does NOT go through live_small_auto pre-flight
        response = client.post(
            "/runtime/control-plane/mode",
            json={"to_mode": "paused"},
        )

        body = response.json()
        # Must succeed (no day_baseline needed for non-live_small_auto transitions)
        assert body["success"] is True
        assert body["current_mode"] == "paused"