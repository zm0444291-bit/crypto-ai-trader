"""Binance WebSocket market data client for real-time kline/candlestick streams.

Binance Spot WebSocket endpoint: wss://stream.binance.com:9443/ws
Stream format: <symbol>@kline_<interval>  e.g. btcusdt@kline_1h

Architecture
============
BinanceWSClient wraps the official Binance combined stream protocol.
It connects to the public kline stream, parses real-time OHLCV updates,
and calls an on_candle callback for each closed/updated candle.
The client runs in a background asyncio task started by start().
Shutdown is coordinated via stop().
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import websockets

from trading.market_data.schemas import CandleData

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"


class BinanceWSClient:
    """Async Binance WebSocket client for kline streams.

    Parameters
    ----------
    symbols : list[str]
        Binance trading symbols in uppercase, e.g. ["BTCUSDT", "ETHUSDT"].
    intervals : list[str]
        Candle intervals, e.g. ["1h", "4h"].
    on_candle : Callable[[str, CandleData], None]
        Callback invoked for each received candle update (may be an
        in-progress candle or a closed one).  Runs on the asyncio event loop.
    """

    def __init__(
        self,
        symbols: list[str],
        intervals: list[str],
        on_candle: Callable[[str, CandleData], None],
    ) -> None:
        self.symbols = symbols
        self.intervals = intervals
        self.on_candle = on_candle

        self._ws: Any = None
        self._reader_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect and start listening.  Idempotent if already running."""
        if self._running:
            return
        self._running = True
        self._reader_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Gracefully disconnect and cancel background tasks."""
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_stream_url(self) -> str:
        """Build Binance combined stream URL for kline subscriptions."""
        streams = [
            f"{sym.lower()}@kline_{intv}"
            for sym in self.symbols
            for intv in self.intervals
        ]
        return f"{BINANCE_WS_URL}/{'/'.join(streams)}"

    async def _run(self) -> None:
        """Main connect + read loop with auto-reconnect on failure."""
        while self._running:
            try:
                url = self._build_stream_url()
                async with websockets.connect(url, ping_interval=30) as ws:
                    self._ws = ws
                    self._ping_task = asyncio.create_task(self._ping_loop(ws))
                    await self._read_loop(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Binance WS error: %s — reconnecting in 5s", exc)
                if self._running:
                    await asyncio.sleep(5)

    async def _ping_loop(self, ws: Any) -> None:
        """Send ping every 30 seconds (handled automatically by websockets lib)."""
        while self._running:
            await asyncio.sleep(30)

    async def _read_loop(self, ws: Any) -> None:
        """Read and dispatch messages until disconnect."""
        async for raw in ws:
            if not self._running:
                break
            try:
                msg = json.loads(raw)
                self._dispatch(msg)
            except json.JSONDecodeError:
                logger.debug("Non-JSON WS message: %s", str(raw)[:100])

    def _dispatch(self, msg: dict[str, Any]) -> None:
        """Parse a Binance kline event and invoke on_candle callback."""
        event = msg.get("e", "")
        if event != "kline":
            return

        kline = msg.get("k", {})
        symbol = kline.get("s", "")
        interval = kline.get("i", "")

        try:
            open_time_ms = int(kline.get("t", 0))
            close_time_ms = int(kline.get("T", 0))
            candle = CandleData(
                symbol=symbol,
                timeframe=interval,
                open_time=datetime.fromtimestamp(open_time_ms / 1000, tz=UTC),
                close_time=datetime.fromtimestamp(close_time_ms / 1000, tz=UTC),
                open=Decimal(str(kline.get("o", "0"))),
                high=Decimal(str(kline.get("h", "0"))),
                low=Decimal(str(kline.get("l", "0"))),
                close=Decimal(str(kline.get("c", "0"))),
                volume=Decimal(str(kline.get("v", "0"))),
                source="binance_ws",
            )
        except Exception as exc:
            logger.warning("Failed to parse kline for %s: %s", symbol, exc)
            return

        try:
            self.on_candle(symbol, candle)
        except Exception as exc:
            logger.warning("on_candle raised for %s: %s", symbol, exc)
