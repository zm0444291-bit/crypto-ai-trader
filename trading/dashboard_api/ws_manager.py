"""WebSocket connection manager for real-time dashboard updates.

Architecture
============
WebSocketManager is a module-level singleton that holds all connected clients,
organised by channel.  Runtime loop components call `broadcast()` after each
significant action; the manager fans out to every subscriber in O(n) where n
is the number of connected dashboard tabs.

Channels
--------
  all       — every message (default for new connections)
  runtime   — cycle / supervisor heartbeat events
  orders    — order lifecycle events
  risk      — risk check results, freeze events
  portfolio — fill / position updates
  market    — live ticker / candle updates (Stage 4b)

Message format
-------------
All messages are JSON objects::

  {
    "channel": "runtime",
    "event_type": "cycle_finished",
    "data": { ... },          # channel-specific payload
    "timestamp": "2026-04-22T09:52:00.000Z"
  }

Connecting
----------
Dashboard tabs open one WebSocket connection on mount and stay connected for
the lifetime of the tab.  The query parameter ``channels`` limits which
channels the client receives (comma-separated).  Example::

  ws://localhost:8000/ws?channels=runtime,orders

If ``channels`` is omitted the client receives all channels.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Channel(StrEnum):
    """Broadcaster channels."""

    ALL = "all"
    RUNTIME = "runtime"
    ORDERS = "orders"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    MARKET = "market"


# ─── Outgoing message shape ──────────────────────────────────────────────────


class WSMessage(BaseModel):
    channel: str
    event_type: str
    data: dict[str, Any]
    timestamp: str


# ─── Per-client state ────────────────────────────────────────────────────────


@dataclass
class ClientState:
    websocket: WebSocket
    channels: set[str]
    connected_at: float = field(default_factory=time.time)
    subscribed: bool = False


# ─── Manager ─────────────────────────────────────────────────────────────────


class WebSocketManager:
    """Thread-safe WebSocket connection registry with channel-based fan-out."""

    def __init__(self) -> None:
        self._clients: dict[int, ClientState] = {}
        self._lock = asyncio.Lock()
        self._next_id: int = 0
        self._ping_task: asyncio.Task[None] | None = None
        self._running: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background keep-alive ping loop (call once at startup)."""
        global _manager
        if self._running:
            return
        _manager = self
        self._running = True
        self._ping_task = asyncio.create_task(self._ping_loop())
        logger.info("WebSocket manager started")

    async def stop(self) -> None:
        """Gracefully close all connections and stop the ping loop."""
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            for cs in list(self._clients.values()):
                try:
                    await cs.websocket.close(code=1001, reason="server shutdown")
                except Exception as exc:
                    logger.debug("Error closing websocket: %s", exc)
            self._clients.clear()
        logger.info("WebSocket manager stopped")

    # ── connection ───────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, channels: list[str]) -> int:
        """Register a new WebSocket client and return its numeric client_id."""
        await websocket.accept()

        # Resolve "all" shorthand
        resolved: set[str] = set(channels) if channels else {Channel.ALL}
        if Channel.ALL in resolved:
            resolved = {c.value for c in Channel}

        client_id = self._next_id
        self._next_id += 1

        cs = ClientState(websocket=websocket, channels=resolved, subscribed=True)
        async with self._lock:
            self._clients[client_id] = cs

        logger.info(
            "WS client %d connected  channels=%s",
            client_id,
            sorted(cs.channels),
        )
        return client_id

    async def disconnect(self, client_id: int) -> None:
        """Remove a client by id."""
        async with self._lock:
            cs = self._clients.pop(client_id, None)
        if cs is not None:
            logger.info("WS client %d disconnected", client_id)

    # ── broadcast ────────────────────────────────────────────────────────────

    async def broadcast(
        self,
        channel: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Fan out a message to all clients subscribed to ``channel``."""
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = WSMessage(
            channel=channel,
            event_type=event_type,
            data=data,
            timestamp=ts,
        )
        raw = payload.model_dump_json()

        # Collect client states outside the lock to avoid nested-lock deadlock
        client_states: list[tuple[int, ClientState]] = []
        async with self._lock:
            for cid in self._clients.keys():
                cs = self._clients.get(cid)
                if cs is not None and cs.subscribed:
                    client_states.append((cid, cs))

        sent = 0
        for cid, cs in client_states:
            # Skip if client didn't subscribe to this channel and isn't an ALL subscriber
            # (exception: broadcast("all") reaches every active client regardless)
            if (
                channel != Channel.ALL
                and Channel.ALL not in cs.channels
                and channel not in cs.channels
            ):
                continue

            # send
            try:
                await cs.websocket.send_text(raw)
                sent += 1
            except Exception as exc:
                logger.warning(
                    "Failed to send to WS client %d: %s — removing",
                    cid,
                    exc,
                )
                await self.disconnect(cid)

        if sent:
            logger.debug(
                "broadcast %s/%s → %d client(s)",
                channel,
                event_type,
                sent,
            )

    # ── ping loop ────────────────────────────────────────────────────────────

    async def _ping_loop(self) -> None:
        """Send ping frames to all clients every 30 s; evict stale ones."""
        while self._running:
            await asyncio.sleep(30)
            if not self._running:
                break

            async with self._lock:
                client_ids = list(self._clients.keys())

            stale: list[int] = []
            for cid in client_ids:
                cs: ClientState | None
                async with self._lock:
                    cs = self._clients.get(cid)
                if cs is None:
                    continue

                try:
                    await cs.websocket.send_json({"type": "ping", "ts": time.time()})
                except Exception:
                    stale.append(cid)

            for cid in stale:
                await self.disconnect(cid)

            if stale:
                logger.info("Ping loop evicted %d stale WS client(s)", len(stale))


# ─── Module-level singleton ──────────────────────────────────────────────────

_manager: WebSocketManager | None = None
_sync_loop: asyncio.AbstractEventLoop | None = None


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Register the asyncio event loop from FastAPI's lifespan.

    After this call, broadcast_from_sync() can dispatch into the loop
    from any thread.  Must be called from the async main thread (lifespan).
    """
    global _sync_loop
    _sync_loop = loop


def get_manager() -> WebSocketManager:
    """Return the process-wide WebSocket manager (lazily created)."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager


# ─── Sync-safe broadcast helper ──────────────────────────────────────────────
# runner.py and paper_cycle.py run in synchronous threads.  We dispatch WS
# broadcasts via asyncio.create_task so they don't block the trading thread.
# The loop reference is registered once from FastAPI's lifespan (async main
# thread) and used for all subsequent thread-safe dispatches.


def broadcast_from_sync(
    channel: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Schedule a WS broadcast from a synchronous thread.

    Uses the event loop registered by register_loop().  Idempotent: if no loop
    is registered yet (server not fully started) the task is discarded harmlessly.
    """
    if _sync_loop is None:
        return

    def _do_broadcast() -> None:
        # run_coroutine_threadsafe returns a Future; we discard it (fire-and-forget)
        asyncio.run_coroutine_threadsafe(
            get_manager().broadcast(channel, event_type, data),
            _sync_loop,
        )

    _do_broadcast()


# ─── FastAPI router ──────────────────────────────────────────────────────────


def _parse_channels(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


async def ws_endpoint(websocket: WebSocket, channels: str | None = None) -> None:
    """FastAPI WebSocket endpoint — one connection per dashboard tab."""
    manager = get_manager()
    client_id = await manager.connect(websocket, _parse_channels(channels))
    try:
        while True:
            try:
                # 61-second timeout — larger than the 30-second ping interval so
                # legitimate clients are never kicked.  On a real message we just
                # acknowledge it.
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=61.0,
                )
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")
                    if msg_type == "pong":
                        pass  # client acknowledged — all good
                    elif msg_type == "subscribe":
                        # Dynamic channel subscription update (future use)
                        new_channels = _parse_channels(msg.get("channels"))
                        async with manager._lock:
                            if client_id in manager._clients:
                                manager._clients[client_id].channels = (
                                    {c.value for c in Channel}
                                    if "all" in new_channels
                                    else set(new_channels)
                                )
                    elif msg_type == "ping":
                        await websocket.send_json(
                            {"type": "pong", "ts": msg.get("ts")}
                        )
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            except TimeoutError:
                # No message in 61 s — client is still connected but idle.
                # Just loop back and let the ping loop do its job.
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(client_id)


router = APIRouter(tags=["websocket"])
router.add_api_websocket_route("/ws", ws_endpoint)
