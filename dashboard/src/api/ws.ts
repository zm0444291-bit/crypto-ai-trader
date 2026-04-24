import { useCallback, useEffect, useRef, useState } from 'react';

const WS_BASE = (import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000').replace('http', 'ws');

export type WsChannel = 'runtime' | 'portfolio' | 'orders' | 'risk' | 'events' | 'market' | 'all';

export interface KlineUpdate {
  symbol: string;
  timeframe: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  open_time: string;
  close_time: string;
  source: string;
}

export interface RiskUpdate {
  event_type: string;
  risk_state: string;
  message: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface WsMessage<T = unknown> {
  channel: string;
  payload: T;
  ts: string;
}

interface UseWebSocketOptions {
  /** Comma-separated channels to subscribe to, or '*' for all. Default: '*'. */
  channels?: string;
  /** Called when connection is established. */
  onOpen?: () => void;
  /** Called on every message received. */
  onMessage?: (msg: WsMessage) => void;
  /** Reconnect delay in ms. Default: 3000. Pass -1 to disable auto-reconnect. */
  reconnectDelay?: number;
}

interface UseWebSocketReturn {
  /** Current connection state. */
  connected: boolean;
  /** Last message received on any subscribed channel. */
  lastMessage: WsMessage | null;
  /** Send a message to the server (future use, e.g. channel subscription changes). */
  send: (msg: object) => void;
  /** Force reconnect. */
  reconnect: () => void;
}

// ── Connection singleton ──────────────────────────────────────────────────────
// One shared WebSocket instance across all hook instances.  The browser
// guarantees sequential delivery of messages; we dispatch by channel
// inside the singleton so every useWebSocket hook receives its relevant
// messages without creating multiple WS connections.

type Listener = (msg: WsMessage) => void;

let _ws: WebSocket | null = null;
let _listeners: Set<Listener> = new Set();
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _explicitClose = false;

function getWsUrl(): string {
  return `${WS_BASE}/ws`;
}

function isOpen(ws: WebSocket): boolean {
  return ws.readyState === WebSocket.OPEN;
}

function ensureWs(onOpen: (() => void) | undefined): WebSocket {
  if (_ws && isOpen(_ws)) return _ws;

  _explicitClose = false;
  const ws = new WebSocket(getWsUrl());
  _ws = ws;

  ws.addEventListener('open', () => {
    onOpen?.();
  });

  ws.addEventListener('message', (ev) => {
    try {
      const msg: WsMessage = JSON.parse(ev.data);
      for (const listener of _listeners) {
        listener(msg);
      }
    } catch {
      // ignore malformed frames
    }
  });

  ws.addEventListener('close', () => {
    _ws = null;
    if (!_explicitClose) {
      _reconnectTimer = setTimeout(() => {
        ensureWs(undefined);
      }, 3000);
    }
  });

  ws.addEventListener('error', () => {
    ws.close();
  });

  return ws;
}

function closeWs() {
  _explicitClose = true;
  if (_reconnectTimer !== null) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
  if (_ws) {
    _ws.close();
    _ws = null;
  }
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useWebSocket({
  onOpen,
  onMessage,
  reconnectDelay = 3000,
}: UseWebSocketOptions = {}): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  onMessageRef.current = onMessage;
  onOpenRef.current = onOpen;

  const listener = useCallback((msg: WsMessage) => {
    setLastMessage(msg);
    onMessageRef.current?.(msg);
  }, []);

  useEffect(() => {
    _listeners.add(listener);
    return () => {
      _listeners.delete(listener);
    };
  }, [listener]);

  useEffect(() => {
    const ws = ensureWs(() => setConnected(true));
    if (isOpen(ws)) setConnected(true);

    const checkClose = setInterval(() => {
      setConnected(_ws !== null && isOpen(_ws));
    }, 1000);

    return () => {
      clearInterval(checkClose);
      closeWs();
      _listeners.delete(listener);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = useCallback((msg: object) => {
    if (_ws && isOpen(_ws)) {
      _ws.send(JSON.stringify(msg));
    }
  }, []);

  const reconnect = useCallback(() => {
    closeWs();
    if (reconnectDelay >= 0) {
      setTimeout(() => ensureWs(undefined), 0);
    }
  }, [reconnectDelay]);

  return { connected, lastMessage, send, reconnect };
}

// ── Channel-specific helpers ───────────────────────────────────────────────────

/** Filter a message by channel. Useful in onMessage callbacks. */
export function channelOf<T = unknown>(msg: WsMessage, channel: WsChannel): msg is WsMessage<T> {
  return msg.channel === channel || msg.channel === 'all';
}
