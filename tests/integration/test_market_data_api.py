from fastapi.testclient import TestClient

from trading.main import app


def test_market_data_status_returns_configured_symbols_and_timeframes():
    client = TestClient(app)

    response = client.get("/market-data/status")

    assert response.status_code == 200
    body = response.json()
    # Status reflects data freshness: fresh/stale when candles exist, unknown when DB is unavailable
    assert body["status"] in ("fresh", "stale", "unknown")
    assert body["live_trading_enabled"] is False
    assert body["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert body["timeframes"] == ["15m", "1h", "4h"]