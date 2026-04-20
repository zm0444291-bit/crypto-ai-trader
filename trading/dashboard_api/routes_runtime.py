"""Dashboard API for runtime loop visibility and control (read-only + write control-plane)."""

import os
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from trading.execution.gate import TRADE_MODES, compute_execution_route
from trading.runtime.config import AppSettings
from trading.runtime.mode import validate_mode_transition
from trading.runtime.reconciliation import (
    BalanceSnapshot,
    PositionSnapshot,
    ReconciliationStatus,
    ReconciliationThresholds,
    run_reconciliation,
)
from trading.runtime.state import get_live_trading_lock, get_trade_mode
from trading.storage.db import create_database_engine, create_session_factory, init_db
from trading.storage.repositories import (
    EventsRepository,
    ExecutionRecordsRepository,
    RuntimeControlRepository,
    ShadowExecutionRepository,
)

router = APIRouter(tags=["runtime"])


def _to_aware_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


class ReconciliationStatusResponse(BaseModel):
    status: ReconciliationStatus
    last_check_time: str | None
    diff_summary: str


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
    # Heartbeat health observability
    heartbeat_stale_alerting: bool  # True if in stale/lost state, False otherwise
    last_recovered_time: str | None  # ISO timestamp of last heartbeat_recovered event
    # Component restart observability
    restart_attempts_ingestion_last_hour: int
    restart_attempts_trading_last_hour: int
    restart_exhausted_ingestion: bool
    restart_exhausted_trading: bool
    last_restart_time: str | None
    # Execution control plane fields
    trade_mode: str
    live_trading_lock_enabled: bool
    execution_route_effective: str
    mode_transition_guard: str | None
    # Shadow execution fields (live_shadow mode)
    shadow_executions_last_hour: int
    last_shadow_time: str | None
    # Reconciliation status
    reconciliation: ReconciliationStatusResponse


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
            heartbeat_stale_alerting=False,
            last_recovered_time=None,
            restart_attempts_ingestion_last_hour=0,
            restart_attempts_trading_last_hour=0,
            restart_exhausted_ingestion=False,
            restart_exhausted_trading=False,
            last_restart_time=None,
            trade_mode="paper_auto",
            live_trading_lock_enabled=False,
            execution_route_effective="paper",
            mode_transition_guard="blocked: unavailable",
            shadow_executions_last_hour=0,
            last_shadow_time=None,
            reconciliation=ReconciliationStatusResponse(
                status=ReconciliationStatus.OK,
                last_check_time=None,
                diff_summary="unavailable",
            ),
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

            # ── reconciliation ───────────────────────────────────────────────────
            # Build local balance/position snapshots from DB fills for reconciliation.
            # This runs on every /runtime/status call to keep the dashboard fresh.
            all_fills = exec_repo.list_fills_chronological()
            local_usdt_balance = Decimal("500")  # initial cash
            local_positions: dict[str, PositionSnapshot] = {}

            for fill in all_fills:
                if fill.side == "BUY":
                    local_usdt_balance -= fill.qty * fill.price + fill.fee_usdt
                    pos = local_positions.get(fill.symbol)
                    if pos is None:
                        local_positions[fill.symbol] = PositionSnapshot(
                            symbol=fill.symbol,
                            qty=fill.qty,
                            avg_entry_price=fill.price,
                        )
                    else:
                        total_qty = pos.qty + fill.qty
                        total_cost = pos.qty * pos.avg_entry_price + fill.qty * fill.price
                        local_positions[fill.symbol] = PositionSnapshot(
                            symbol=fill.symbol,
                            qty=total_qty,
                            avg_entry_price=total_cost / total_qty,
                        )
                elif fill.side == "SELL":
                    local_usdt_balance += fill.qty * fill.price - fill.fee_usdt
                    pos = local_positions.get(fill.symbol)
                    if pos is not None:
                        new_qty = pos.qty - fill.qty
                        if new_qty <= Decimal("0"):
                            del local_positions[fill.symbol]
                        else:
                            local_positions[fill.symbol] = PositionSnapshot(
                                symbol=fill.symbol,
                                qty=new_qty,
                                avg_entry_price=pos.avg_entry_price,
                            )

            local_balance_snapshots = [
                BalanceSnapshot(asset="USDT", free=local_usdt_balance, locked=Decimal("0"))
            ]
            local_position_snapshots = list(local_positions.values())

            reconciliation_result = run_reconciliation(
                local_balances=local_balance_snapshots,
                local_positions=local_position_snapshots,
                thresholds=ReconciliationThresholds(),
            )

            # ── shadow execution fields ──────────────────────────────────────────
            shadow_repo = ShadowExecutionRepository(session)
            shadow_executions_last_hour = shadow_repo.count_last_hour(one_hour_ago)
            recent_shadows = shadow_repo.list_recent_shadow(limit=1)
            last_shadow_time: str | None = None
            if recent_shadows:
                last_shadow_aware = _to_aware_utc(recent_shadows[0].created_at)
                last_shadow_time = last_shadow_aware.isoformat() if last_shadow_aware else None

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

            # ── heartbeat health observability: stale alerting and recovery ──
            last_recovered_time: str | None = None
            latest_heartbeat_lost_time: datetime | None = None
            latest_heartbeat_recovered_time: datetime | None = None
            for e in all_events:
                if e.event_type == "heartbeat_recovered":
                    t = _to_aware_utc(e.created_at)
                    is_newer = (
                        latest_heartbeat_recovered_time is None
                        or (t is not None and t > latest_heartbeat_recovered_time)
                    )
                    if t and is_newer:
                        latest_heartbeat_recovered_time = t
                        last_recovered_time = t.isoformat() if t else None
                elif e.event_type == "heartbeat_lost":
                    t = _to_aware_utc(e.created_at)
                    if t and (latest_heartbeat_lost_time is None or t > latest_heartbeat_lost_time):
                        latest_heartbeat_lost_time = t
            # heartbeat_stale_alerting = True when the most recent heartbeat_lost
            # is newer than the most recent heartbeat_recovered (or no recovery yet).
            heartbeat_stale_alerting: bool = (
                latest_heartbeat_lost_time is not None
                and (
                    latest_heartbeat_recovered_time is None
                    or latest_heartbeat_lost_time > latest_heartbeat_recovered_time
                )
            )

            # ── component restart observability ───────────────────────────────
            restart_attempts_ingestion_last_hour = 0
            restart_attempts_trading_last_hour = 0
            restart_exhausted_ingestion: bool | None = None
            restart_exhausted_trading: bool | None = None
            last_restart_time: str | None = None

            for e in all_events:
                if e.event_type not in (
                    "component_restart_attempted",
                    "component_restart_succeeded",
                    "component_restart_exhausted",
                ):
                    continue

                t = _to_aware_utc(e.created_at)
                if last_restart_time is None and t is not None:
                    last_restart_time = t.isoformat()

                ctx: dict[str, Any] = e.context_json or {}
                component = str(ctx.get("component", "")).lower()
                if e.event_type == "component_restart_attempted":
                    if t is not None and t >= one_hour_ago:
                        if component == "ingestion":
                            restart_attempts_ingestion_last_hour += 1
                        elif component == "trading":
                            restart_attempts_trading_last_hour += 1
                elif e.event_type == "component_restart_exhausted":
                    if component == "ingestion" and restart_exhausted_ingestion is None:
                        restart_exhausted_ingestion = True
                    elif component == "trading" and restart_exhausted_trading is None:
                        restart_exhausted_trading = True
                elif e.event_type == "component_restart_succeeded":
                    if component == "ingestion" and restart_exhausted_ingestion is None:
                        restart_exhausted_ingestion = False
                    elif component == "trading" and restart_exhausted_trading is None:
                        restart_exhausted_trading = False

            if restart_exhausted_ingestion is None:
                restart_exhausted_ingestion = False
            if restart_exhausted_trading is None:
                restart_exhausted_trading = False

        current_mode = get_trade_mode(session_factory)
        lock_state = get_live_trading_lock(session_factory)
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
            heartbeat_stale_alerting=heartbeat_stale_alerting,
            last_recovered_time=last_recovered_time,
            restart_attempts_ingestion_last_hour=restart_attempts_ingestion_last_hour,
            restart_attempts_trading_last_hour=restart_attempts_trading_last_hour,
            restart_exhausted_ingestion=restart_exhausted_ingestion,
            restart_exhausted_trading=restart_exhausted_trading,
            last_restart_time=last_restart_time,
            trade_mode=current_mode,
            live_trading_lock_enabled=lock_state.enabled,
            execution_route_effective=compute_execution_route(current_mode),
            mode_transition_guard=transition_guard.reason,
            shadow_executions_last_hour=shadow_executions_last_hour,
            last_shadow_time=last_shadow_time,
            reconciliation=ReconciliationStatusResponse(
                status=reconciliation_result.status,
                last_check_time=datetime.now(UTC).isoformat(),
                diff_summary=(
                    f"balance_diff={reconciliation_result.balance_diff_usdt} USDT, "
                    f"position_diffs={reconciliation_result.position_diff_count}, "
                    f"global_pause={reconciliation_result.global_pause_recommended}"
                ),
            ),
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
            heartbeat_stale_alerting=False,
            last_recovered_time=None,
            restart_attempts_ingestion_last_hour=0,
            restart_attempts_trading_last_hour=0,
            restart_exhausted_ingestion=False,
            restart_exhausted_trading=False,
            last_restart_time=None,
            trade_mode="paper_auto",
            live_trading_lock_enabled=False,
            execution_route_effective="paper",
            mode_transition_guard="blocked: unavailable",
            shadow_executions_last_hour=0,
            last_shadow_time=None,
            reconciliation=ReconciliationStatusResponse(
                status=ReconciliationStatus.OK,
                last_check_time=None,
                diff_summary="unavailable",
            ),
        )


class ModeChangeRequest(BaseModel):
    """Request body for changing the trade mode."""

    to_mode: TRADE_MODES
    allow_live_unlock: bool = False
    reason: str | None = None


class ModeChangeResponse(BaseModel):
    """Structured response for mode change operations."""

    success: bool
    current_mode: str
    guard_reason: str


class LiveLockChangeRequest(BaseModel):
    """Request body for changing the live trading lock state."""

    enabled: bool
    reason: str | None = None


class LiveLockChangeResponse(BaseModel):
    """Structured response for live-lock change operations."""

    success: bool
    lock_enabled: bool
    reason: str


class ControlPlaneResponse(BaseModel):
    """Read-only snapshot of the runtime control plane."""

    trade_mode: str
    lock_enabled: bool
    lock_reason: str | None
    execution_route: str
    transition_guard_to_live_small_auto: str


class SystemExitRequest(BaseModel):
    """Request body for local one-click system exit."""

    confirm: bool = True


class SystemExitResponse(BaseModel):
    """Response for local one-click system exit."""

    success: bool
    message: str


def _perform_local_shutdown(current_pid: int) -> None:
    """Terminate local runtime/backend/dashboard processes for one-click exit."""
    patterns = (
        "trading.runtime.cli --supervisor",
        "trading.runtime.cli --interval",
        "trading.runtime.cli --once",
        "uvicorn trading.main:app",
        "npm run dev",
        "vite",
    )
    for pattern in patterns:
        subprocess.run(
            ["pkill", "-f", pattern],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        os.kill(current_pid, signal.SIGTERM)
    except OSError:
        pass


def schedule_local_shutdown(delay_seconds: float = 0.8) -> None:
    """Schedule local shutdown after the API response has been sent."""
    current_pid = os.getpid()

    def _worker() -> None:
        time.sleep(delay_seconds)
        _perform_local_shutdown(current_pid)

    thread = threading.Thread(target=_worker, daemon=True, name="local-system-exit")
    thread.start()


@router.post("/runtime/control-plane/mode", response_model=ModeChangeResponse)
def set_mode(body: ModeChangeRequest) -> ModeChangeResponse:
    """Change the runtime trade mode."""
    try:
        settings = AppSettings()
        engine = create_database_engine(settings.database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)
    except Exception:
        return ModeChangeResponse(
            success=False,
            current_mode="paper_auto",
            guard_reason="blocked: unavailable",
        )

    try:
        current_mode = get_trade_mode(session_factory)
        lock_state = get_live_trading_lock(session_factory)

        if current_mode == body.to_mode:
            return ModeChangeResponse(
                success=True,
                current_mode=current_mode,
                guard_reason="same_mode",
            )

        guard = validate_mode_transition(
            current_mode,
            body.to_mode,
            lock_enabled=lock_state.enabled,
            allow_live_unlock=body.allow_live_unlock,
        )

        if not guard.allowed:
            return ModeChangeResponse(
                success=False,
                current_mode=current_mode,
                guard_reason=guard.reason,
            )

        with session_factory() as session:
            events_repo = EventsRepository(session)
            repo = RuntimeControlRepository(session)
            before_mode = repo.get_trade_mode()
            repo.set_trade_mode(body.to_mode)
            new_mode = repo.get_trade_mode()

            events_repo.record_event(
                event_type="runtime_mode_changed",
                severity="info",
                component="control_plane",
                message=f"Mode changed: {before_mode} -> {new_mode}",
                context={
                    "before_mode": before_mode,
                    "after_mode": new_mode,
                    "operator_source": "api",
                    "operator_reason": body.reason,
                },
            )

        return ModeChangeResponse(
            success=True,
            current_mode=new_mode,
            guard_reason=guard.reason,
        )
    except Exception:
        return ModeChangeResponse(
            success=False,
            current_mode="paper_auto",
            guard_reason="blocked: unavailable",
        )


@router.post("/runtime/control-plane/live-lock", response_model=LiveLockChangeResponse)
def set_live_lock(body: LiveLockChangeRequest) -> LiveLockChangeResponse:
    """Change the live trading lock state."""
    try:
        settings = AppSettings()
        engine = create_database_engine(settings.database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)
    except Exception:
        return LiveLockChangeResponse(
            success=False,
            lock_enabled=False,
            reason="blocked: unavailable",
        )

    try:
        with session_factory() as session:
            events_repo = EventsRepository(session)
            repo = RuntimeControlRepository(session)
            before_lock = repo.get_live_trading_lock()
            repo.set_live_trading_lock(enabled=body.enabled, reason=body.reason)
            lock = repo.get_live_trading_lock()

            events_repo.record_event(
                event_type="runtime_live_lock_changed",
                severity="info",
                component="control_plane",
                message=f"Live lock changed: {before_lock.enabled} -> {body.enabled}",
                context={
                    "before_enabled": before_lock.enabled,
                    "after_enabled": lock.enabled,
                    "operator_source": "api",
                    "operator_reason": body.reason,
                },
            )

        return LiveLockChangeResponse(
            success=True,
            lock_enabled=lock.enabled,
            reason=lock.reason or "ok",
        )
    except Exception:
        return LiveLockChangeResponse(
            success=False,
            lock_enabled=False,
            reason="blocked: unavailable",
        )


@router.get("/runtime/control-plane", response_model=ControlPlaneResponse)
def read_control_plane() -> ControlPlaneResponse:
    """Return a read-only snapshot of the runtime control plane.

    This endpoint never mutates state — it is purely informational.
    Defaults are safe values when the DB is unavailable.
    """
    try:
        settings = AppSettings()
        engine = create_database_engine(settings.database_url)
        init_db(engine)
        session_factory = create_session_factory(engine)
    except Exception:
        return ControlPlaneResponse(
            trade_mode="paper_auto",
            lock_enabled=False,
            lock_reason=None,
            execution_route="paper",
            transition_guard_to_live_small_auto="blocked: unavailable",
        )

    try:
        current_mode = get_trade_mode(session_factory)
        lock_state = get_live_trading_lock(session_factory)
        transition_guard = validate_mode_transition(
            current_mode,
            "live_small_auto",
            lock_enabled=lock_state.enabled,
            allow_live_unlock=False,
        )

        return ControlPlaneResponse(
            trade_mode=current_mode,
            lock_enabled=lock_state.enabled,
            lock_reason=lock_state.reason,
            execution_route=compute_execution_route(current_mode),
            transition_guard_to_live_small_auto=transition_guard.reason,
        )
    except Exception:
        return ControlPlaneResponse(
            trade_mode="paper_auto",
            lock_enabled=False,
            lock_reason=None,
            execution_route="paper",
            transition_guard_to_live_small_auto="blocked: unavailable",
        )


@router.post("/runtime/system/exit", response_model=SystemExitResponse)
def exit_local_system(body: SystemExitRequest, request: Request) -> SystemExitResponse:
    """One-click local exit from Dashboard.

    This is local-ops only: it schedules shutdown of runtime/backend/dashboard
    processes and then terminates the current backend process.
    """
    if not body.confirm:
        return SystemExitResponse(success=False, message="blocked: confirmation_required")

    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return SystemExitResponse(success=False, message="blocked: local_only")

    schedule_local_shutdown()
    return SystemExitResponse(success=True, message="shutdown_scheduled")
