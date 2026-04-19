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

export async function getRecentEvents(): Promise<{ events: EventsSummary[] }> {
  return apiFetch<{ events: EventsSummary[] }>('/events/recent');
}
