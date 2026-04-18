from fastapi import APIRouter

from trading.runtime.health import HealthStatus, get_health_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
def read_health() -> HealthStatus:
    """Return runtime health for smoke checks and dashboard boot."""

    return get_health_status()
