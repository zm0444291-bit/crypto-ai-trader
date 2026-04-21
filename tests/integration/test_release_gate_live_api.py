"""Integration tests for GET /runtime/release-gate/live — read-only pre-flight visualization.

These tests verify:
1. Happy path returns the expected structure with all sections populated
2. Fail-closed behavior when critical dependencies are unavailable
3. Read-only guarantee: calling the endpoint does NOT write events to the DB
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from trading.main import app
from trading.storage.db import Base, create_database_engine, create_session_factory
from trading.storage.repositories import (
    EventsRepository,
    RuntimeControlRepository,
)


class TestReleaseGateLiveHappyPath:
    """Happy path: all dependencies available and baseline set today."""

    def test_response_structure_complete(self, tmp_path, monkeypatch):
        """Response must contain all required top-level fields and sections."""
        database_url = f"sqlite:///{tmp_path}/happy.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        now = datetime.now(UTC)
        today_str = now.strftime("%Y-%m-%d")

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paper_auto")
            repo.set_live_trading_lock(enabled=False, reason=None)
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="Day baseline set to 500.0",
                context={"date": today_str, "baseline": "500.0"},
            )
            events_repo.record_event(
                event_type="supervisor_heartbeat",
                severity="info",
                component="supervisor",
                message="Supervisor heartbeat",
                context={
                    "ingest_thread_alive": True,
                    "trading_thread_alive": True,
                    "uptime_seconds": 120,
                },
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()

        # Top-level structure
        assert "generated_at" in body, "missing generated_at"
        assert "environment" in body, "missing environment"
        assert "control_plane" in body, "missing control_plane"
        assert "risk" in body, "missing risk"
        assert "health" in body, "missing health"
        assert "checks" in body, "missing checks"
        assert "summary" in body, "missing summary"

        # environment fields
        env = body["environment"]
        assert "database_ok" in env
        assert "binance_key_present" in env
        assert "binance_secret_present" in env
        assert "exchanges_yaml_ok" in env

        # control_plane fields
        cp = body["control_plane"]
        assert "trade_mode" in cp
        assert "lock_enabled" in cp
        assert "execution_route" in cp
        assert "transition_guard_to_live_small_auto" in cp

        # risk fields
        risk = body["risk"]
        assert "resolved_risk_state" in risk
        assert "day_start_equity" in risk
        assert "current_equity" in risk
        assert "daily_pnl_pct" in risk
        assert "risk_reason" in risk

        # health fields
        health = body["health"]
        assert "supervisor_alive" in health
        assert "ingestion_thread_alive" in health
        assert "trading_thread_alive" in health
        assert "heartbeat_stale_alerting" in health

        # summary fields
        summary = body["summary"]
        assert "allow_live_shadow" in summary
        assert "allow_live_small_auto_dry_run" in summary
        assert "blocked_reasons" in summary
        assert isinstance(summary["blocked_reasons"], list)

        # checks must be a list of {code, status, message}
        for check in body["checks"]:
            assert "code" in check
            assert "status" in check
            assert check["status"] in ("pass", "fail", "warn")
            assert "message" in check

    def test_env_keys_are_never_included(self, tmp_path, monkeypatch):
        """BINANCE_API_KEY / SECRET presence booleans are True but values are never returned."""
        monkeypatch.setenv("BINANCE_API_KEY", "a-real-key-should-not-appear")
        monkeypatch.setenv("BINANCE_API_SECRET", "a-real-secret-should-not-appear")
        database_url = f"sqlite:///{tmp_path}/keys.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        # Keys must NOT appear in the response (values not returned)
        text = response.text
        assert "a-real-key" not in text, "API key must not appear in response body"
        assert "a-real-secret" not in text, "API secret must not appear in response body"

        # But the presence booleans must be True
        assert body["environment"]["binance_key_present"] is True
        assert body["environment"]["binance_secret_present"] is True

    def test_checks_include_expected_codes(self, tmp_path, monkeypatch):
        """All expected check codes are present when system is healthy."""
        database_url = f"sqlite:///{tmp_path}/checks.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )
            uptime_secs = 1
            events_repo.record_event(
                event_type="supervisor_heartbeat",
                severity="info",
                component="supervisor",
                message="heartbeat",
                context={
                    "ingest_thread_alive": True,
                    "trading_thread_alive": True,
                    "uptime_seconds": uptime_secs,
                },
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        codes = {c["code"] for c in response.json()["checks"]}

        # Environment checks
        assert "env:binance_api_key" in codes
        assert "env:binance_api_secret" in codes
        assert "env:exchanges_yaml" in codes
        assert "env:database" in codes
        # Health checks
        assert "health:supervisor_alive" in codes
        assert "health:ingestion_alive" in codes
        assert "health:trading_alive" in codes
        assert "health:heartbeat_stale" in codes
        # Control plane checks
        assert "cp:live_lock" in codes
        assert "cp:trade_mode" in codes
        assert "cp:mode_transition_to_live_small_auto_dry_run" in codes
        # Risk check
        assert "risk:state" in codes

    def test_live_shadow_allowed_when_healthy(self, tmp_path, monkeypatch):
        """With DB OK + healthy heartbeat + no lock, allow_live_shadow = True."""
        database_url = f"sqlite:///{tmp_path}/shadow_allowed.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paper_auto")
            repo.set_live_trading_lock(enabled=False, reason=None)
            events_repo = EventsRepository(session)
            uptime_secs = 10
            events_repo.record_event(
                event_type="supervisor_heartbeat",
                severity="info",
                component="supervisor",
                message="heartbeat",
                context={
                    "ingest_thread_alive": True,
                    "trading_thread_alive": True,
                    "uptime_seconds": uptime_secs,
                },
            )
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        assert body["summary"]["allow_live_shadow"] is True

    def test_live_small_auto_dry_run_blocked_without_keys(self, tmp_path, monkeypatch):
        """Without BINANCE_API_KEY/SECRET, allow_live_small_auto_dry_run = False."""
        # Ensure env vars are NOT set
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        database_url = f"sqlite:///{tmp_path}/no_keys.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        assert body["summary"]["allow_live_small_auto_dry_run"] is False
        reasons = body["summary"]["blocked_reasons"]
        assert any("BINANCE_API_KEY" in r for r in reasons), (
            f"Expected API_KEY in blocked_reasons: {reasons}"
        )
        assert any("BINANCE_API_SECRET" in r for r in reasons), (
            f"Expected API_SECRET in blocked_reasons: {reasons}"
        )

    def test_dry_run_is_blocked_when_mode_transition_guard_blocks(self, tmp_path, monkeypatch):
        """paper_auto cannot dry-run live_small_auto directly (must pass live_shadow first)."""
        monkeypatch.setenv("BINANCE_API_KEY", "key")
        monkeypatch.setenv("BINANCE_API_SECRET", "secret")
        database_url = f"sqlite:///{tmp_path}/mode_guard.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_trade_mode("paper_auto")
            repo.set_live_trading_lock(enabled=False, reason=None)
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        assert body["summary"]["allow_live_small_auto_dry_run"] is False
        reasons = body["summary"]["blocked_reasons"]
        assert any("must transition through live_shadow first" in r for r in reasons), (
            f"Expected transition guard reason in blocked_reasons: {reasons}"
        )


class TestReleaseGateLiveFailClosed:
    """API must fail-closed when critical dependencies are missing."""

    def test_no_day_baseline_risk_unavailable_blocks_dry_run(self, tmp_path, monkeypatch):
        """Without day_baseline_set, risk state is unavailable — fail-closed blocks dry-run."""
        database_url = f"sqlite:///{tmp_path}/no_baseline.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            uptime_secs = 1
            events_repo.record_event(
                event_type="supervisor_heartbeat",
                severity="info",
                component="supervisor",
                message="heartbeat",
                context={
                    "ingest_thread_alive": True,
                    "trading_thread_alive": True,
                    "uptime_seconds": uptime_secs,
                },
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        # Risk state should be unavailable
        assert body["risk"]["resolved_risk_state"] == "unavailable"
        # And a warn check should be present
        codes = {c["code"] for c in body["checks"]}
        assert "risk:state" in codes
        risk_check = next(c for c in body["checks"] if c["code"] == "risk:state")
        assert risk_check["status"] == "warn"
        assert body["summary"]["allow_live_small_auto_dry_run"] is False

    def test_heartbeat_stale_blocks_live_shadow(self, tmp_path, monkeypatch):
        """Stale heartbeat (no recent heartbeat_recovered) blocks allow_live_shadow."""
        database_url = f"sqlite:///{tmp_path}/stale_heartbeat.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            # heartbeat_lost but no heartbeat_recovered → stale
            events_repo.record_event(
                event_type="heartbeat_lost",
                severity="warning",
                component="supervisor",
                message="heartbeat lost",
                context={},
            )
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        assert body["health"]["heartbeat_stale_alerting"] is True
        assert body["summary"]["allow_live_shadow"] is False

    def test_lock_enabled_blocks_live_small_auto_dry_run(self, tmp_path, monkeypatch):
        """Live trading lock enabled → allow_live_small_auto_dry_run = False."""
        database_url = f"sqlite:///{tmp_path}/lock_enabled.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("BINANCE_API_KEY", "key")
        monkeypatch.setenv("BINANCE_API_SECRET", "secret")
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            repo = RuntimeControlRepository(session)
            repo.set_live_trading_lock(enabled=True, reason="Operator initiated")
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)
        response = client.get("/runtime/release-gate/live")
        body = response.json()

        assert body["control_plane"]["lock_enabled"] is True
        assert body["summary"]["allow_live_small_auto_dry_run"] is False
        reasons = body["summary"]["blocked_reasons"]
        assert any(
            ("真实交易锁" in r) or ("模式迁移约束" in r) for r in reasons
        ), f"Expected lock or transition guard reason in blocked_reasons: {reasons}"


class TestReleaseGateLiveReadOnly:
    """Calling the endpoint must NOT write any events to the DB."""

    def test_no_events_written_on_call(self, tmp_path, monkeypatch):
        """Calling GET /runtime/release-gate/live does not increment event count."""
        database_url = f"sqlite:///{tmp_path}/readonly.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            initial_count = len(events_repo.list_recent(limit=10000))

        client = TestClient(app)

        # Call the endpoint
        response = client.get("/runtime/release-gate/live")
        assert response.status_code == 200

        # Check event count is unchanged (no new events written)
        with session_factory() as session:
            events_repo = EventsRepository(session)
            final_count = len(events_repo.list_recent(limit=10000))

        assert final_count == initial_count, (
            f"Expected no new events written by GET /runtime/release-gate/live. "
            f"Before={initial_count}, after={final_count}. "
            f"Endpoint must be read-only."
        )

    def test_duplicate_calls_produce_same_count(self, tmp_path, monkeypatch):
        """Multiple calls do not accumulate events — confirms idempotent read-only behavior."""
        database_url = f"sqlite:///{tmp_path}/idempotent.sqlite3"
        engine = create_database_engine(database_url)
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", database_url)
        session_factory = create_session_factory(engine)

        with session_factory() as session:
            events_repo = EventsRepository(session)
            events_repo.record_event(
                event_type="day_baseline_set",
                severity="info",
                component="runtime",
                message="baseline",
                context={"date": datetime.now(UTC).strftime("%Y-%m-%d"), "baseline": "500.0"},
            )

        client = TestClient(app)

        for _ in range(3):
            response = client.get("/runtime/release-gate/live")
            assert response.status_code == 200

        with session_factory() as session:
            events_repo = EventsRepository(session)
            final_count = len(events_repo.list_recent(limit=10000))

        # Should still be exactly 1 (the initial baseline event)
        assert final_count == 1, f"Expected exactly 1 event after 3 calls, got {final_count}"
