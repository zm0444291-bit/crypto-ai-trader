"""Market data WebSocket bridge: Binance WS → dashboard WS.

This module owns the Binance WebSocket connection and forwards every
incoming candle tick to the dashboard via the shared dashboard WS manager.
It is started/stopped via the FastAPI lifespan.

Architecture
============
BinanceMarketDataManager  ──(on_candle callback)──>  dispatch_ws_broadcast
                                                          │
                                              WebSocketManager (singleton)
                                                          │
                                               dashboard clients (WS /ws)

Usage
=====
Started automatically by main.py's lifespan.  To broadcast a market data
update from anywhere else in the codebase, import broadcast_from_sync from
ws_manager and emit directly on the "market_data" channel.
"""

import logging

from trading.dashboard_api.ws_manager import Channel, broadcast_from_sync
from trading.market_data.binance_ws_client import BinanceWSClient
from trading.market_data.schemas import CandleData

logger = logging.getLogger(__name__)

# All supported symbols and intervals for WS streaming
_WS_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
_WS_INTERVALS = ["1m", "5m", "15m", "1h", "4h"]


class BinanceMarketDataManager:
    """Owns the Binance WS connection and bridges ticks to the dashboard WS."""

    def __init__(self) -> None:
        self._client: BinanceWSClient | None = None
        self._running = False

    # ── Public API ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Binance WebSocket and start receiving kline updates."""
        if self._running:
            return
        self._running = True

        def on_candle(symbol: str, candle: CandleData) -> None:
            """Called on every Binance kline update — bridge to dashboard WS."""
            try:
                broadcast_from_sync(
                    channel=Channel.MARKET.value,
                    event_type="kline_update",
                    data={
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe,
                        "open": str(candle.open),
                        "high": str(candle.high),
                        "low": str(candle.low),
                        "close": str(candle.close),
                        "volume": str(candle.volume),
                        "open_time": candle.open_time.isoformat(),
                        "close_time": candle.close_time.isoformat(),
                        "source": candle.source,
                    },
                )
            except Exception as exc:
                logger.debug("broadcast_from_sync raised: %s", exc)

        self._client = BinanceWSClient(
            symbols=_WS_SYMBOLS,
            intervals=_WS_INTERVALS,
            on_candle=on_candle,
        )
        await self._client.start()
        logger.info(
            "BinanceMarketDataManager started — streaming %s %s",
            _WS_SYMBOLS,
            _WS_INTERVALS,
        )

    async def stop(self) -> None:
        """Gracefully disconnect from Binance WebSocket."""
        if not self._running:
            return
        self._running = False
        if self._client:
            await self._client.stop()
            self._client = None
        logger.info("BinanceMarketDataManager stopped")


# ── Module-level singleton ──────────────────────────────────────────────────────

_manager: BinanceMarketDataManager | None = None


def get_market_data_manager() -> BinanceMarketDataManager:
    global _manager
    if _manager is None:
        _manager = BinanceMarketDataManager()
    return _manager
