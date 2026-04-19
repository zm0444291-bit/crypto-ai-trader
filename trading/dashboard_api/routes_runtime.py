"""Dashboard API for runtime loop visibility (read-only)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from trading.execution.gate import compute_execution_route
from trading.runtime.config import AppSettings
from trading.runtime.mode import validate_mode_transition
from trading.runtime.state import get_live_trading_lock, get_trade_mode
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import EventsRepository, ExecutionRecordsRepository

router = APIRouter(tags=["runtime"])


def _to_aware_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


class RuntimeStatusResponse(BaseModel):
    last_cycle_status: str | None
    last_cycle_time: datetime | None
    last_error_message: str | None
    cycles_last_hour: int
    orders_last_hour: int
    # Supervisor heartbeat fields
    supervisor_alive: bool | None
    ingestion_thread_alive: bool | None
    trading_thread_alive: bool | None
    uptime_seconds: int | None
    last_heartbeat_time: str | None
    last_component_error: str | None
    # Execution control plane fields
    trade_mode: str
    live_trading_lock_enabled: bool
    execution_route_effective: str
    mode_transition_guard: str | None


@router.get("/runtime/status", response_model=RuntimeStatusResponse)
def read_runtime_status() -> RuntimeStatusResponse:
    """Return runtime loop visibility metrics derived from events and order records.

    All fields default to safe values (null/0) when data is absent to keep the
    endpoint resilient — never returns 500 due to missing data.
    """
    try:
        settings = AppSettings()
        engine = create_database_engine(settings.database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)
    except Exception:
        return RuntimeStatusResponse(
            last_cycle_status=None,
            last_cycle_time=None,
            last_error_message=None,
            cycles_last_hour=0,
            orders_last_hour=0,
            supervisor_alive=None,
            ingestion_thread_alive=None,
            trading_thread_alive=None,
            uptime_seconds=None,
            last_heartbeat_time=None,
            last_component_error=None,
            trade_mode="paper_auto",
            live_trading_lock_enabled=False,
            execution_route_effective="paper",
            mode_transition_guard="transition_allowed",
        )

    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    try:
        with session_factory() as session:
            events_repo = EventsRepository(session)
            exec_repo = ExecutionRecordsRepository(session)

            all_events = events_repo.list_recent(limit=500)

            # ── last cycle status & time: newest cycle_finished ──
            last_cycle_status: str | None = None
            last_cycle_time: datetime | None = None
            for e in all_events:
                if e.event_type == "cycle_finished":
                    ctx: dict[str, Any] = e.context_json or {}
                    last_cycle_status = ctx.get("status")
                    last_cycle_time = e.created_at
                    break

            # ── last_error_message: newest cycle_error ──
            last_error_message: str | None = None
            for e in all_events:
                if e.event_type == "cycle_error":
                    last_error_message = e.message
                    break

            # ── cycles_last_hour: count in reverse (oldest-first) scan ──
            cycles_last_hour = sum(
                1
                for e in reversed(all_events)
                if e.event_type == "cycle_started"
                and (_to_aware_utc(e.created_at) or datetime.min.replace(tzinfo=UTC))
                >= one_hour_ago
            )

            # ── orders_last_hour: count orders created in the last hour ──
            recent_orders = exec_repo.list_recent_orders(limit=500)
            orders_last_hour = sum(
                1
                for o in recent_orders
                if (_to_aware_utc(o.created_at) or datetime.min.replace(tzinfo=UTC))
                >= one_hour_ago
            )

            # ── supervisor heartbeat fields (2-minute freshness window) ──
            heartbeat_cutoff = now - timedelta(minutes=2)
            supervisor_alive: bool | None = None
            ingestion_thread_alive: bool | None = None
            trading_thread_alive: bool | None = None
            uptime_seconds: int | None = None
            last_heartbeat_time: str | None = None
            most_recent_heartbeat: Any = None

            for e in all_events:
                if e.event_type == "supervisor_heartbeat":
                    most_recent_heartbeat = e
                    break

            if most_recent_heartbeat is not None:
                hb_created = _to_aware_utc(most_recent_heartbeat.created_at)
                last_heartbeat_time = hb_created.isoformat() if hb_created else None
                if hb_created and hb_created >= heartbeat_cutoff:
                    supervisor_alive = True
                elif hb_created:
                    supervisor_alive = False
                ctx = most_recent_heartbeat.context_json or {}
                _raw = ctx.get("ingest_thread_alive")
                ingestion_thread_alive = bool(_raw) if _raw is not None else None
                _raw = ctx.get("trading_thread_alive")
                trading_thread_alive = bool(_raw) if _raw is not None else None
                _raw = ctx.get("uptime_seconds")
                uptime_seconds = int(_raw) if _raw is not None else None

            # ── last_component_error: most recent supervisor_component_error ──
            last_component_error: str | None = None
            for e in all_events:
                if e.event_type == "supervisor_component_error":
                    last_component_error = e.message
                    break

        current_mode = get_trade_mode()
        lock_state = get_live_trading_lock()
        transition_guard = validate_mode_transition(
            current_mode,
            "live_small_auto",
            lock_enabled=lock_state.enabled,
            allow_live_unlock=False,
        )

        return RuntimeStatusResponse(
            last_cycle_status=last_cycle_status,
            last_cycle_time=last_cycle_time,
            last_error_message=last_error_message,
            cycles_last_hour=cycles_last_hour,
            orders_last_hour=orders_last_hour,
            supervisor_alive=supervisor_alive,
            ingestion_thread_alive=ingestion_thread_alive,
            trading_thread_alive=trading_thread_alive,
            uptime_seconds=uptime_seconds,
            last_heartbeat_time=last_heartbeat_time,
            last_component_error=last_component_error,
            trade_mode=current_mode,
            live_trading_lock_enabled=lock_state.enabled,
            execution_route_effective=compute_execution_route(current_mode),
            mode_transition_guard=transition_guard.reason,
        )

    except Exception:
        return RuntimeStatusResponse(
            last_cycle_status=None,
            last_cycle_time=None,
            last_error_message=None,
            cycles_last_hour=0,
            orders_last_hour=0,
            supervisor_alive=None,
            ingestion_thread_alive=None,
            trading_thread_alive=None,
            uptime_seconds=None,
            last_heartbeat_time=None,
            last_component_error=None,
            trade_mode="paper_auto",
            live_trading_lock_enabled=False,
            execution_route_effective="paper",
            mode_transition_guard="transition_allowed",
        )
