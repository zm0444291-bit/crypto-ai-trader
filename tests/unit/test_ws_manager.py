"""Unit tests for trading.dashboard_api.ws_manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.dashboard_api.ws_manager import (
    Channel,
    ClientState,
    WebSocketManager,
    _parse_channels,
    broadcast_from_sync,
    get_manager,
    register_loop,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def ws_manager() -> WebSocketManager:
    """Fresh manager instance for each test."""
    m = WebSocketManager()
    m._running = False  # disable background ping loop
    return m


@pytest.fixture
def mock_websocket() -> MagicMock:
    """Mock FastAPI WebSocket that tracks sent text."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


# ─── Channel parsing ─────────────────────────────────────────────────────────


class TestParseChannels:
    def test_none_returns_empty_list(self) -> None:
        assert _parse_channels(None) == []

    def test_empty_string_returns_empty_list(self) -> None:
        assert _parse_channels("") == []

    def test_single_channel(self) -> None:
        assert _parse_channels("runtime") == ["runtime"]

    def test_multiple_channels(self) -> None:
        result = _parse_channels("runtime,orders,risk")
        assert result == ["runtime", "orders", "risk"]

    def test_whitespace_stripped(self) -> None:
        result = _parse_channels(" runtime , orders ")
        assert result == ["runtime", "orders"]

    def test_empty_segments_ignored(self) -> None:
        result = _parse_channels("runtime,,orders")
        assert result == ["runtime", "orders"]


# ─── ClientState ─────────────────────────────────────────────────────────────


class TestClientState:
    def test_default_connected_at_is_set(self) -> None:
        ws = MagicMock()
        cs = ClientState(websocket=ws, channels={"runtime"})
        assert cs.connected_at > 0

    def test_subscribed_defaults_to_false(self) -> None:
        ws = MagicMock()
        cs = ClientState(websocket=ws, channels={"runtime"})
        assert cs.subscribed is False


# ─── Lifecycle ───────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_start_idempotent(self) -> None:
        """start() must be callable without a running loop (before app startup)."""
        m = WebSocketManager()
        # Calling start() without a running loop should not raise.
        # The ping task is created when the loop is running.
        m._running = True  # simulate "started" flag
        m.start()  # second call should not raise
        assert m._running is True

    def test_stop_closes_all_clients(self) -> None:
        """stop() must be callable synchronously."""
        m = WebSocketManager()
        m._running = False
        # stop() is async but returns None immediately when _running=False
        # and _ping_task is None. Verify it doesn't raise.
        result = asyncio.run(m.stop())
        assert result is None

    def test_stop_graceful_with_clients(self) -> None:
        """stop() closes all open connections."""
        async def _test() -> None:
            m = WebSocketManager()
            m.start()

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            cid = await m.connect(ws, ["runtime"])
            assert cid in m._clients

            await m.stop()

            assert cid not in m._clients
            ws.close.assert_called_once()

        asyncio.run(_test())


# ─── Connect / Disconnect ────────────────────────────────────────────────────


class TestConnect:
    def test_connect_returns_incrementing_ids(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws1 = MagicMock()
            ws1.accept = AsyncMock()
            ws1.close = AsyncMock()
            ws1.send_text = AsyncMock()
            ws1.send_json = AsyncMock()

            ws2 = MagicMock()
            ws2.accept = AsyncMock()
            ws2.close = AsyncMock()
            ws2.send_text = AsyncMock()
            ws2.send_json = AsyncMock()

            cid1 = await m.connect(ws1, ["runtime"])
            cid2 = await m.connect(ws2, ["orders"])
            assert cid1 == 0
            assert cid2 == 1

        asyncio.run(_test())

    def test_connect_all_channels_resolves_to_all_enum_values(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            cid = await m.connect(ws, ["all"])
            async with m._lock:
                cs = m._clients[cid]
            assert cs.channels == {c.value for c in Channel}

        asyncio.run(_test())

    def test_connect_specific_channels(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            cid = await m.connect(ws, ["runtime", "orders"])
            async with m._lock:
                cs = m._clients[cid]
            assert cs.channels == {"runtime", "orders"}

        asyncio.run(_test())

    def test_connect_accepts_websocket(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            await m.connect(ws, ["runtime"])
            ws.accept.assert_called_once()

        asyncio.run(_test())


class TestDisconnect:
    def test_disconnect_removes_client(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            cid = await m.connect(ws, ["runtime"])
            await m.disconnect(cid)
            assert cid not in m._clients

        asyncio.run(_test())

    def test_disconnect_unknown_id_noops(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False
            # Should not raise
            await m.disconnect(9999)

        asyncio.run(_test())


# ─── Broadcast ───────────────────────────────────────────────────────────────


class TestBroadcast:
    def test_broadcast_to_subscribed_client(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            await m.connect(ws, ["runtime"])
            await m.broadcast("runtime", "cycle_finished", {"cycles": 1})
            ws.send_text.assert_called_once()
            sent = ws.send_text.call_args[0][0]
            assert '"channel":"runtime"' in sent
            assert '"event_type":"cycle_finished"' in sent
            assert '"cycles":1' in sent

        asyncio.run(_test())

    def test_broadcast_to_multiple_subscribers(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws1 = MagicMock()
            ws1.accept = AsyncMock()
            ws1.send_text = AsyncMock()
            ws1.close = AsyncMock()
            ws1.send_json = AsyncMock()

            ws2 = MagicMock()
            ws2.accept = AsyncMock()
            ws2.send_text = AsyncMock()
            ws2.close = AsyncMock()
            ws2.send_json = AsyncMock()

            await m.connect(ws1, ["runtime"])
            await m.connect(ws2, ["runtime"])
            await m.broadcast("runtime", "heartbeat", {"ts": 123})

            assert ws1.send_text.call_count == 1
            assert ws2.send_text.call_count == 1

        asyncio.run(_test())

    def test_broadcast_skips_non_subscribed_channel(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            await m.connect(ws, ["orders"])
            await m.broadcast("runtime", "heartbeat", {})
            ws.send_text.assert_not_called()

        asyncio.run(_test())

    def test_broadcast_all_channel_reaches_all_clients(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws_runtime = MagicMock()
            ws_runtime.accept = AsyncMock()
            ws_runtime.send_text = AsyncMock()
            ws_runtime.close = AsyncMock()
            ws_runtime.send_json = AsyncMock()

            ws_orders = MagicMock()
            ws_orders.accept = AsyncMock()
            ws_orders.send_text = AsyncMock()
            ws_orders.close = AsyncMock()
            ws_orders.send_json = AsyncMock()

            await m.connect(ws_runtime, ["runtime"])
            await m.connect(ws_orders, ["orders"])

            await m.broadcast("all", "market_event", {"price": 100})

            ws_runtime.send_text.assert_called_once()
            ws_orders.send_text.assert_called_once()

        asyncio.run(_test())

    def test_broadcast_disconnects_stale_client(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_text = AsyncMock(side_effect=Exception("broken pipe"))
            ws.close = AsyncMock()
            ws.send_json = AsyncMock()

            cid = await m.connect(ws, ["runtime"])
            await m.broadcast("runtime", "ping", {})
            # client should be removed
            assert cid not in m._clients

        asyncio.run(_test())

    def test_broadcast_message_includes_timestamp(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m._running = False

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            await m.connect(ws, ["runtime"])
            await m.broadcast("runtime", "test_event", {})
            sent = ws.send_text.call_args[0][0]
            assert '"timestamp":' in sent

        asyncio.run(_test())


# ─── broadcast_from_sync ─────────────────────────────────────────────────────


class TestBroadcastFromSync:
    def test_noop_when_loop_not_registered(self) -> None:
        # Should not raise, task is discarded
        broadcast_from_sync("runtime", "test", {"foo": 1})

    def test_broadcast_via_registered_loop(self) -> None:
        async def _test() -> None:
            m = WebSocketManager()
            m.start()

            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.close = AsyncMock()
            ws.send_text = AsyncMock()
            ws.send_json = AsyncMock()

            await m.connect(ws, ["runtime"])

            # Register this test's loop
            loop = asyncio.get_running_loop()
            register_loop(loop)

            # Broadcast from "sync" context (callable from background thread)
            broadcast_from_sync("runtime", "sync_test", {"value": 42})

            # Give the task a moment to run on the loop
            await asyncio.sleep(0.05)

            ws.send_text.assert_called()
            sent = ws.send_text.call_args[0][0]
            assert '"event_type":"sync_test"' in sent
            assert '"value":42' in sent

            await m.stop()

        asyncio.run(_test())

    def test_broadcast_from_sync_noop_when_loop_none(self) -> None:
        # Simulate no loop registered by patching _sync_loop
        import trading.dashboard_api.ws_manager as wsm

        old_loop = wsm._sync_loop
        wsm._sync_loop = None
        try:
            broadcast_from_sync("runtime", "test", {})  # must not raise
        finally:
            wsm._sync_loop = old_loop


# ─── get_manager singleton ────────────────────────────────────────────────────


class TestGetManager:
    def test_returns_same_instance(self) -> None:
        # Reset global
        import trading.dashboard_api.ws_manager as wsm

        old = wsm._manager
        wsm._manager = None
        try:
            m1 = get_manager()
            m2 = get_manager()
            assert m1 is m2
        finally:
            wsm._manager = old

    def test_instance_is_websocket_manager(self) -> None:
        import trading.dashboard_api.ws_manager as wsm

        old = wsm._manager
        wsm._manager = None
        try:
            m = get_manager()
            assert isinstance(m, WebSocketManager)
        finally:
            wsm._manager = old


# ─── Channel enum ────────────────────────────────────────────────────────────


class TestChannel:
    def test_all_six_values(self) -> None:
        expected = {"all", "runtime", "orders", "risk", "portfolio", "market"}
        assert {c.value for c in Channel} == expected

    def test_is_str_enum(self) -> None:
        assert Channel.RUNTIME == "runtime"
        assert Channel.RISK == "risk"
        assert Channel.MARKET == "market"
