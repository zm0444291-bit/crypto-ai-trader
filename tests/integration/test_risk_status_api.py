from fastapi.testclient import TestClient

from trading.main import app


def test_risk_status_returns_daily_loss_thresholds_and_state():
    client = TestClient(app)

    response = client.get(
        "/risk/status",
        params={"day_start_equity": "500", "current_equity": "475"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["risk_profile"]["name"] == "small_balanced"
    assert body["risk_state"] == "degraded"
    assert body["daily_pnl_pct"] == "-5"
    assert body["thresholds"]["caution"]["pct"] == "5"
    assert body["thresholds"]["caution"]["amount_usdt"] == "25"
    assert body["thresholds"]["no_new_positions"]["pct"] == "7"
    assert body["thresholds"]["no_new_positions"]["amount_usdt"] == "35"
    assert body["thresholds"]["global_pause"]["pct"] == "10"
    assert body["thresholds"]["global_pause"]["amount_usdt"] == "50"
    assert body["max_trade_risk_usdt"] == "7.125"
    assert body["max_trade_risk_hard_cap_usdt"] == "9.5"
    assert body["max_symbol_position_usdt"] == "142.5"
    assert body["max_total_position_usdt"] == "332.5"


def test_risk_status_selects_profile_from_current_equity():
    client = TestClient(app)

    response = client.get(
        "/risk/status",
        params={"day_start_equity": "2000", "current_equity": "2000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["risk_profile"]["name"] == "medium_conservative"
    assert body["risk_state"] == "normal"
    assert body["thresholds"]["caution"]["pct"] == "3"
    assert body["thresholds"]["no_new_positions"]["pct"] == "5"
    assert body["thresholds"]["global_pause"]["pct"] == "7"


def test_risk_status_rejects_invalid_day_start_equity():
    client = TestClient(app)

    response = client.get(
        "/risk/status",
        params={"day_start_equity": "0", "current_equity": "500"},
    )

    assert response.status_code == 400
    assert "day_start_equity" in response.json()["detail"]
