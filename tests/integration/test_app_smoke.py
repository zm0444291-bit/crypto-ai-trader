from fastapi.testclient import TestClient

from trading.main import app


def test_health_endpoint_returns_runtime_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["trade_mode"] == "paper_auto"
    assert response.json()["live_trading_enabled"] is False
