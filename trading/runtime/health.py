from pydantic import BaseModel


class HealthStatus(BaseModel):
    """API response for runtime health."""

    status: str
    app_name: str
    trade_mode: str
    live_trading_enabled: bool


def get_health_status() -> HealthStatus:
    """Return static Milestone 0 health state."""

    return HealthStatus(
        status="ok",
        app_name="crypto-ai-trader",
        trade_mode="paper_auto",
        live_trading_enabled=False,
    )
