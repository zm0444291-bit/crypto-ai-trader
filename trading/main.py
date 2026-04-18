from fastapi import FastAPI

from trading.dashboard_api.routes_health import router as health_router

app = FastAPI(title="Crypto AI Trader")
app.include_router(health_router)
