"""Health check endpoint — reads heartbeats and risk state from the DB."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter

from trading.runtime.health import get_health_status
from trading.storage.db import create_database_engine, create_session_factory
from trading.storage.repositories import EventsRepository

router = APIRouter(tags=["health"])


def _latest_event(event_type: str) -> dict[str, object]:
    """Return {'created_at': iso_str | None, 'context': dict} for the most recent event of type."""
    from trading.runtime.config import AppSettings

    settings = AppSettings()
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        repo = EventsRepository(session)
        evt = repo.get_latest_event_by_type(event_type)
        if evt is None:
            return {"created_at": None, "context": {}}
        return {
            "created_at": evt.created_at.isoformat() if evt.created_at else None,
            "context": dict(evt.context_json) if evt.context_json else {},
        }


@router.get("/health")
def read_health() -> dict[str, object]:
    """Return runtime health for smoke checks and dashboard boot.

    Pulls live data from the DB: heartbeats, latest equity baseline,
    and the most recent risk_state event.
    """
    try:
        ingestion_evt = _latest_event("supervisor_heartbeat")
        trading_evt = _latest_event("loop_finished")

        ingestion_ts: str | None = (
            str(ingestion_evt["created_at"])
            if ingestion_evt.get("created_at")
            else None
        )
        trading_ts: str | None = (
            str(trading_evt["created_at"])
            if trading_evt.get("created_at")
            else None
        )

        baseline_evt: dict[str, object] = _latest_event("equity_baseline_set")
        day_start_raw = baseline_evt.get("context", {}).get("baseline")  # type: ignore[attr-defined]

        portfolio_evt: dict[str, object] = _latest_event("portfolio_update")
        current_equity_raw = portfolio_evt.get("context", {}).get("total_equity")  # type: ignore[attr-defined]

        risk_evt: dict[str, object] = _latest_event("risk_state_changed")
        risk_state = "unknown"
        risk_profile_name = "unknown"
        if risk_evt:
            ctx: dict[str, object] = risk_evt.get("context", {}) or {}  # type: ignore[assignment]
            risk_state = str(ctx.get("new_state", "unknown"))
            risk_profile_name = str(ctx.get("profile", "unknown"))

        day_start = Decimal(str(day_start_raw)) if day_start_raw else Decimal("0")
        current_equity = (
            Decimal(str(current_equity_raw)) if current_equity_raw else Decimal("0")
        )

        daily_pnl = Decimal("0")
        if day_start > 0:
            daily_pnl = (current_equity - day_start) / day_start * Decimal("100")

        hs = get_health_status(
            risk_state=risk_state,
            risk_profile_name=risk_profile_name,
            daily_pnl_pct=daily_pnl,
            current_equity_usdt=current_equity,
            day_start_equity_usdt=day_start,
            ingestion_heartbeat=ingestion_ts,
            trading_heartbeat=trading_ts,
        )
        return hs.model_dump()

    except Exception as exc:
        hs = get_health_status(risk_state="unknown")
        result = hs.model_dump()
        result.setdefault("alert_messages", []).append(f"Health check error: {exc}")
        return result
