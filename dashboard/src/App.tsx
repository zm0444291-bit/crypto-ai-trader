import { useEffect, useState } from 'react';
import {
  getHealth,
  getRiskStatus,
  getPortfolioStatus,
  getRecentOrders,
  getRecentEvents,
  type HealthStatus,
  type RiskStatus,
  type PortfolioStatus,
  type OrderSummary,
  type EventsSummary,
} from './api/client';

// ── Helpers ──────────────────────────────────────────────────────────────────

function riskDot(state: string): string {
  switch (state) {
    case 'normal':          return 'dot-normal';
    case 'degraded':        return 'dot-degraded';
    case 'no_new_positions':return 'dot-no-new';
    case 'global_pause':     return 'dot-global';
    case 'emergency_stop':  return 'dot-emergency';
    default:                return 'dot-disabled';
  }
}

function severityBadge(severity: string): string {
  switch (severity) {
    case 'info':    return 'badge badge-info';
    case 'warning': return 'badge badge-warning';
    case 'error':   return 'badge badge-danger';
    case 'success': return 'badge badge-success';
    default:        return 'badge badge-info';
  }
}

function fmtNum(v: string | number, decimals = 2): string {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(n)) return '—';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtPct(v: string | number): string {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch {
    return iso;
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SafetyBanner() {
  return (
    <div className="safety-banner">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <span>Read-only paper-mode dashboard — no trade execution, no live trading controls</span>
    </div>
  );
}

function OfflineNotice() {
  return (
    <div className="offline-notice">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>Backend offline — showing placeholder data</span>
    </div>
  );
}

function StatusStrip({ health, risk }: { health: HealthStatus | null; risk: RiskStatus | null }) {
  const offline = !health && !risk;
  return (
    <div className="status-strip">
      <div className="status-pill">
        <span className="label">Mode</span>
        <span className="value">{health?.trade_mode ?? '—'}</span>
      </div>
      <div className="status-pill">
        <span className="label">Live Trading</span>
        <span className="value">
          {health
            ? health.live_trading_enabled ? 'Enabled' : 'Disabled'
            : '—'}
        </span>
      </div>
      <div className="status-pill">
        <span className={`dot ${risk ? riskDot(risk.risk_state) : 'dot-disabled'}`} />
        <span className="label">Risk State</span>
        <span className="value">{risk?.risk_state ?? (offline ? '—' : 'normal')}</span>
      </div>
      <div className="status-pill">
        <span className="label">Profile</span>
        <span className="value">{risk?.risk_profile.name ?? '—'}</span>
      </div>
    </div>
  );
}

function MetricsGrid({ portfolio, risk }: { portfolio: PortfolioStatus | null; risk: RiskStatus | null }) {
  const equity    = portfolio?.total_equity_usdt ?? null;
  const cash      = portfolio?.cash_balance_usdt ?? null;
  const pnlPct    = risk?.daily_pnl_pct ?? null;
  const maxRisk   = risk?.max_trade_risk_usdt ?? null;

  const pnlClass = pnlPct !== null
    ? (parseFloat(pnlPct) >= 0 ? 'positive' : 'negative')
    : '';

  return (
    <div className="metrics-grid">
      <div className="metric-card">
        <div className="metric-label">Account Equity</div>
        <div className="metric-value">{equity !== null ? `$${fmtNum(equity)}` : '—'}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Cash Balance</div>
        <div className="metric-value">{cash !== null ? `$${fmtNum(cash)}` : '—'}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Today PnL</div>
        <div className={`metric-value ${pnlClass}`}>{pnlPct !== null ? fmtPct(pnlPct) : '—'}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Max Trade Risk</div>
        <div className="metric-value">{maxRisk !== null ? `$${fmtNum(maxRisk)}` : '—'}</div>
      </div>
    </div>
  );
}

function PositionsSection({ positions }: { positions: PortfolioStatus['positions'] | null }) {
  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Positions</span>
      </div>
      {positions === null || positions.length === 0 ? (
        <div className="empty-state">No open positions</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Avg Entry</th>
                <th>Mkt Price</th>
                <th>Mkt Value</th>
                <th>Unreal. PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.unrealized_pnl_usdt);
                const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
                return (
                  <tr key={i}>
                    <td>{p.symbol}</td>
                    <td>{fmtNum(p.qty, 4)}</td>
                    <td>${fmtNum(p.avg_entry_price)}</td>
                    <td>${fmtNum(p.market_price)}</td>
                    <td>${fmtNum(p.market_value_usdt)}</td>
                    <td className={pnlClass}>{fmtNum(p.unrealized_pnl_usdt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OrdersSection({ orders }: { orders: OrderSummary[] | null }) {
  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Recent Orders</span>
      </div>
      {orders === null || orders.length === 0 ? (
        <div className="empty-state">No recent orders</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Status</th>
                <th>Notional</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{o.symbol}</td>
                  <td className={o.side === 'BUY' ? 'side-buy' : 'side-sell'}>{o.side}</td>
                  <td>{o.status}</td>
                  <td>${fmtNum(o.requested_notional_usdt)}</td>
                  <td>{fmtTime(o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EventsSection({ events }: { events: EventsSummary[] | null }) {
  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Recent Events</span>
      </div>
      {events === null || events.length === 0 ? (
        <div className="empty-state">No recent events</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Component</th>
                <th>Type</th>
                <th>Message</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td><span className={severityBadge(e.severity)}>{e.severity}</span></td>
                  <td>{e.component}</td>
                  <td>{e.event_type}</td>
                  <td>{e.message}</td>
                  <td>{fmtTime(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [health,   setHealth]   = useState<HealthStatus | null>(null);
  const [risk,      setRisk]      = useState<RiskStatus | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [orders,    setOrders]    = useState<OrderSummary[] | null>(null);
  const [events,    setEvents]    = useState<EventsSummary[] | null>(null);

  const offline = !health && !risk && !portfolio && !orders && !events;

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => {});

    getRiskStatus(500, 500)
      .then(setRisk)
      .catch(() => {});

    getPortfolioStatus(500)
      .then(setPortfolio)
      .catch(() => {});

    getRecentOrders()
      .then((r) => setOrders(r.orders))
      .catch(() => {});

    getRecentEvents()
      .then((r) => setEvents(r.events))
      .catch(() => {});
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Trading Control Room</h1>
      </header>

      <SafetyBanner />

      {offline && <OfflineNotice />}

      <StatusStrip health={health} risk={risk} />

      <MetricsGrid portfolio={portfolio} risk={risk} />
      <PositionsSection positions={portfolio?.positions ?? null} />
      <OrdersSection orders={orders} />
      <EventsSection events={events} />
    </div>
  );
}
