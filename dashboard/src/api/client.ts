const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface HealthStatus {
  status: string;
  trade_mode: string;
  live_trading_enabled: boolean;
}

export interface MarketDataStatus {
  symbols: string[];
  timeframes: string[];
  connected: boolean;
}

export interface RiskStatus {
  day_start_equity: string;
  current_equity: string;
  risk_profile: { name: string };
  risk_state: string;
  daily_pnl_pct: string;
  max_trade_risk_usdt: string;
  reason: string;
}

export interface PositionSummary {
  symbol: string;
  qty: string;
  avg_entry_price: string;
  market_price: string;
  market_value_usdt: string;
  unrealized_pnl_usdt: string;
}

export interface PortfolioStatus {
  cash_balance_usdt: string;
  total_equity_usdt: string;
  unrealized_pnl_usdt: string;
  positions: PositionSummary[];
}

export interface OrderSummary {
  id: number;
  symbol: string;
  side: string;
  status: string;
  requested_notional_usdt: string;
  created_at: string;
}

export interface EventsSummary {
  id: number;
  event_type: string;
  severity: string;
  component: string;
  message: string;
  created_at: string;
  context?: Record<string, unknown>;
}

export interface RuntimeStatus {
  last_cycle_status: string | null;
  last_cycle_time: string | null;
  last_error_message: string | null;
  cycles_last_hour: number;
  orders_last_hour: number;
  supervisor_alive: boolean | null;
  ingestion_thread_alive: boolean | null;
  trading_thread_alive: boolean | null;
  uptime_seconds: number | null;
  last_heartbeat_time: string | null;
  last_component_error: string | null;
  trade_mode: string;
  live_trading_lock_enabled: boolean;
  execution_route_effective: string;
  mode_transition_guard: string | null;
  shadow_executions_last_hour: number;
  last_shadow_time: string | null;
}

export interface ControlPlaneResponse {
  trade_mode: string;
  lock_enabled: boolean;
  lock_reason: string | null;
  execution_route: string;
  transition_guard_to_live_small_auto: string;
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText} for ${path}`);
  }
  return res.json() as Promise<T>;
}

// ── API functions ─────────────────────────────────────────────────────────────

export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>('/health');
}

export async function getMarketDataStatus(): Promise<MarketDataStatus> {
  return apiFetch<MarketDataStatus>('/market-data/status');
}

export async function getRiskStatus(
  dayStartEquity = 500,
  currentEquity = 500,
): Promise<RiskStatus> {
  return apiFetch<RiskStatus>(
    `/risk/status?day_start_equity=${dayStartEquity}&current_equity=${currentEquity}`,
  );
}

export async function getPortfolioStatus(
  initialCashUsdt = 500,
): Promise<PortfolioStatus> {
  return apiFetch<PortfolioStatus>(`/portfolio/status?initial_cash_usdt=${initialCashUsdt}`);
}

export async function getRecentOrders(): Promise<{ orders: OrderSummary[] }> {
  return apiFetch<{ orders: OrderSummary[] }>('/orders/recent');
}

export async function getRecentEvents(opts?: {
  limit?: number;
  event_type?: string;
}): Promise<{ events: EventsSummary[] }> {
  const params = new URLSearchParams();
  if (opts?.limit !== undefined) params.set('limit', String(opts.limit));
  if (opts?.event_type) params.set('event_type', opts.event_type);
  const query = params.toString();
  return apiFetch<{ events: EventsSummary[] }>(`/events/recent${query ? '?' + query : ''}`);
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  return apiFetch<RuntimeStatus>('/runtime/status');
}

// ── Analytics types ──────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  current_equity_usdt: string;
  day_start_equity_usdt: string;
  daily_pnl_usdt: string;
  daily_pnl_pct: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_pct: string;
  avg_win_usdt: string;
  avg_loss_usdt: string;
  equity_snapshots: Array<{ timestamp: string; equity_usdt: string }>;
  daily_pnl_history: Array<{ date: string; pnl_usdt: string }>;
}

export async function getAnalyticsSummary(): Promise<AnalyticsSummary> {
  return apiFetch<AnalyticsSummary>('/analytics/summary');
}

export async function getRecentEventsFiltered(opts: {
  limit?: number;
  severity?: string;
  component?: string;
  event_type?: string;
}): Promise<{ events: EventsSummary[] }> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set('limit', String(opts.limit));
  if (opts.severity) params.set('severity', opts.severity);
  if (opts.component) params.set('component', opts.component);
  if (opts.event_type) params.set('event_type', opts.event_type);
  const query = params.toString();
  return apiFetch<{ events: EventsSummary[] }>(`/events/recent${query ? '?' + query : ''}`);
}
