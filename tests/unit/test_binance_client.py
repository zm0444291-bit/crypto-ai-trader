from decimal import Decimal

import httpx

from trading.market_data.binance_client import BinanceKlineClient


def test_fetch_klines_normalizes_binance_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["interval"] == "15m"
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json=[
                [
                    1776532800000,
                    "100.0",
                    "110.0",
                    "90.0",
                    "105.0",
                    "12.5",
                    1776533699999,
                    "0",
                    1,
                    "0",
                    "0",
                    "0",
                ]
            ],
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
    client = BinanceKlineClient(client=http_client)

    candles = client.fetch_klines("BTCUSDT", "15m", limit=2)

    assert len(candles) == 1
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].timeframe == "15m"
    assert candles[0].open == Decimal("100.0")
    assert candles[0].close == Decimal("105.0")
    assert candles[0].open_time.tzinfo is not None


def test_fetch_klines_raises_for_http_error():
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"msg": "bad"})),
        base_url="https://api.binance.com",
    )
    client = BinanceKlineClient(client=http_client)

    try:
        client.fetch_klines("BTCUSDT", "15m")
    except httpx.HTTPStatusError:
        assert True
    else:
        raise AssertionError("Expected HTTPStatusError")