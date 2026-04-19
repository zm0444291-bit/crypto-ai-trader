from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from trading.market_data.schemas import CandleData

# Default timeout for Binance API requests: (connect, read) in seconds
_DEFAULT_TIMEOUT = (5.0, 10.0)


class BinanceKlineClient:
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self._client = client

    def fetch_klines(self, symbol: str, interval: str, limit: int = 100) -> list[CandleData]:
        """Fetch public spot klines from Binance and return normalized candles."""
        if self._client is not None:
            client = self._client
        else:
            client = httpx.Client(base_url=self.base_url, timeout=_DEFAULT_TIMEOUT)
        try:
            response = client.get(
                "/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            response.raise_for_status()
        finally:
            if self._client is None:
                client.close()
        data: list[list[Any]] = response.json()
        return [self._parse_kline(kline, symbol, interval) for kline in data]

    def _parse_kline(self, kline: list[Any], symbol: str, interval: str) -> CandleData:
        open_time_ms = kline[0]
        open_time = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC)
        close_time = datetime.fromtimestamp(kline[6] / 1000, tz=UTC)
        return CandleData(
            symbol=symbol,
            timeframe=interval,
            open_time=open_time,
            close_time=close_time,
            open=Decimal(kline[1]),
            high=Decimal(kline[2]),
            low=Decimal(kline[3]),
            close=Decimal(kline[4]),
            volume=Decimal(kline[5]),
            source="binance",
        )
