from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class HealthStatus(BaseModel):
    """API response for runtime health."""

    status: str = "ok"
    app_name: str = "crypto-ai-trader"
    trade_mode: str
    live_trading_enabled: bool
    # Component heartbeats (null = never started)
    ingestion_heartbeat: str | None = Field(
        description="ISO timestamp of last ingestion heartbeat", default=None
    )
    trading_heartbeat: str | None = Field(
        description="ISO timestamp of last trading loop heartbeat", default=None
    )
    # Risk state
    risk_state: str = Field(
        default="unknown",
        description=(
            "Current risk state: normal|degraded|no_new_positions|global_pause|emergency_stop"
        ),
    )
    risk_profile_name: str = Field(
        description="Name of the active risk profile", default="unknown"
    )
    daily_pnl_pct: Decimal = Field(
        description="Today's PnL as a percentage", default=Decimal("0")
    )
    current_equity_usdt: Decimal = Field(
        description="Current account equity in USDT", default=Decimal("0")
    )
    day_start_equity_usdt: Decimal = Field(
        description="Equity at the start of the day in USDT", default=Decimal("0")
    )
    # Alerts
    stale_warning: bool = Field(
        description="True if heartbeat is stale (> 5 min since last beat)", default=False
    )
    alert_messages: list[str] = Field(
        description="Active warning/critical messages", default_factory=list
    )


def _heartbeat_age_seconds(heartbeat: str | None) -> float | None:
    """Return seconds since *heartbeat* ISO string, or None if heartbeat is None."""
    if heartbeat is None:
        return None
    try:
        hb = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now().astimezone(UTC) - hb).total_seconds()


def get_health_status(
    risk_state: str = "unknown",
    risk_profile_name: str = "unknown",
    daily_pnl_pct: Decimal = Decimal("0"),
    current_equity_usdt: Decimal = Decimal("0"),
    day_start_equity_usdt: Decimal = Decimal("0"),
    ingestion_heartbeat: str | None = None,
    trading_heartbeat: str | None = None,
) -> HealthStatus:
    """Build a rich HealthStatus from live runtime data.

    Pass None for risk fields when no trading cycle has run yet.
    """
    # Determine stale warning
    heartbeats = [
        (ingestion_heartbeat, "ingestion"),
        (trading_heartbeat, "trading"),
    ]
    max_age = 0.0
    stale_msgs: list[str] = []
    for hb, name in heartbeats:
        age = _heartbeat_age_seconds(hb)
        if age is not None:
            max_age = max(max_age, age)
        elif hb is None:
            stale_msgs.append(f"{name} has never started")

    stale_warning = max_age > 300 if max_age > 0 else False
    if stale_warning:
        stale_msgs.insert(0, f"No heartbeat for {int(max_age)}s")

    # Determine overall status
    if risk_state in ("global_pause", "emergency_stop"):
        status = "degraded"
    elif risk_state == "no_new_positions":
        status = "degraded"
    elif stale_warning:
        status = "degraded"
    else:
        status = "ok"

    return HealthStatus(
        status=status,
        app_name="crypto-ai-trader",
        trade_mode="paper_auto",
        live_trading_enabled=False,
        risk_state=risk_state,
        risk_profile_name=risk_profile_name,
        daily_pnl_pct=daily_pnl_pct,
        current_equity_usdt=current_equity_usdt,
        day_start_equity_usdt=day_start_equity_usdt,
        ingestion_heartbeat=ingestion_heartbeat,
        trading_heartbeat=trading_heartbeat,
        stale_warning=stale_warning,
        alert_messages=stale_msgs,
    )
