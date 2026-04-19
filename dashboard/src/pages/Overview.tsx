import { useEffect, useState } from 'react';
import {
  getHealth,
  getRiskStatus,
  getPortfolioStatus,
  getRecentOrders,
  getRecentEvents,
  getRuntimeStatus,
  type HealthStatus,
  type RiskStatus,
  type PortfolioStatus,
  type OrderSummary,
  type EventsSummary,
  type RuntimeStatus,
} from '../api/client';
import { riskDot, severityBadge, fmtNum, fmtPct, fmtTime, SafetyBanner, OfflineNotice } from '../lib';

// ── Placeholder data ──────────────────────────────────────────────────────────

const PLACEHOLDER_RISK: RiskStatus = {
  day_start_equity: '500',
  current_equity: '500',
  risk_profile: { name: 'small_balanced' },
  risk_state: 'normal',
  daily_pnl_pct: '0',
  max_trade_risk_usdt: '7.5',
  reason: 'placeholder — backend offline',
};

const PLACEHOLDER_PORTFOLIO: PortfolioStatus = {
  cash_balance_usdt: '500',
  total_equity_usdt: '500',
  unrealized_pnl_usdt: '0',
  positions: [],
};

const PLACEHOLDER_EVENTS: EventsSummary[] = [
  {
    id: -1,
    event_type: 'backend_unavailable',
    severity: 'warning',
    component: 'dashboard',
    message: 'Backend offline — placeholder data shown',
    created_at: new Date().toISOString(),
  },
];

const PLACEHOLDER_RUNTIME: RuntimeStatus = {
  last_cycle_status: null,
  last_cycle_time: null,
  last_error_message: 'backend unavailable',
  cycles_last_hour: 0,
  orders_last_hour: 0,
};

// ── Sub-components ───────────────────────────────────────────────────────────

function LastUpdatedStamp({ date }: { date: Date | null }) {
  if (!date) return null;
  return (
    <span className="last-updated">
      Updated {date.toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })}
    </span>
  );
}

function StatusStrip({
  health,
  risk,
  healthFailed,
  riskFailed,
}: {
  health: HealthStatus | null;
  risk: RiskStatus | null;
  healthFailed: boolean;
  riskFailed: boolean;
}) {
  const displayRisk = riskFailed ? PLACEHOLDER_RISK : risk;
  return (
    <div className="status-strip">
      <div className="status-pill">
        <span className="label">Mode</span>
        <span className="value">
          {health?.trade_mode ?? (healthFailed ? 'paper_auto' : '—')}
        </span>
      </div>
      <div className="status-pill">
        <span className="label">Live Trading</span>
        <span className="value">
          {health
            ? health.live_trading_enabled ? 'Enabled' : 'Disabled'
            : (healthFailed ? 'Disabled' : '—')}
        </span>
      </div>
      <div className="status-pill">
        <span className={`dot ${displayRisk ? riskDot(displayRisk.risk_state) : (riskFailed ? 'dot-placeholder' : 'dot-disabled')}`} />
        <span className="label">Risk State</span>
        <span className="value">{displayRisk?.risk_state ?? (riskFailed ? 'normal' : '—')}</span>
      </div>
      <div className="status-pill">
        <span className="label">Profile</span>
        <span className="value">{displayRisk?.risk_profile.name ?? (riskFailed ? 'small_balanced' : '—')}</span>
      </div>
    </div>
  );
}

function MetricsGrid({
  portfolio,
  risk,
  riskFailed,
  portfolioFailed,
}: {
  portfolio: PortfolioStatus | null;
  risk: RiskStatus | null;
  riskFailed: boolean;
  portfolioFailed: boolean;
}) {
  const displayPortfolio = portfolioFailed ? PLACEHOLDER_PORTFOLIO : portfolio;
  const displayRisk      = riskFailed ? PLACEHOLDER_RISK : risk;

  const equity   = displayPortfolio?.total_equity_usdt ?? null;
  const cash     = displayPortfolio?.cash_balance_usdt ?? null;
  const pnlPct   = displayRisk?.daily_pnl_pct ?? null;
  const maxRisk  = displayRisk?.max_trade_risk_usdt ?? null;

  const pnlClass = pnlPct !== null
    ? (parseFloat(pnlPct) >= 0 ? 'positive' : 'negative')
    : (riskFailed ? 'placeholder' : '');

  return (
    <div className="metrics-grid">
      <div className="metric-card">
        <div className="metric-label">Account Equity</div>
        <div className={`metric-value ${portfolioFailed && equity === null ? 'placeholder' : ''}`}>
          {equity !== null ? `$${fmtNum(equity)}` : (portfolioFailed ? '$500.00' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Cash Balance</div>
        <div className={`metric-value ${portfolioFailed && cash === null ? 'placeholder' : ''}`}>
          {cash !== null ? `$${fmtNum(cash)}` : (portfolioFailed ? '$500.00' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Today PnL</div>
        <div className={`metric-value ${pnlClass}`}>
          {pnlPct !== null ? fmtPct(pnlPct) : (riskFailed ? '+0.00%' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Max Trade Risk</div>
        <div className={`metric-value ${riskFailed && maxRisk === null ? 'placeholder' : ''}`}>
          {maxRisk !== null ? `$${fmtNum(maxRisk)}` : (riskFailed ? '$7.50' : '—')}
        </div>
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

function EventsSection({
  events,
  isPlaceholder = false,
}: {
  events: EventsSummary[] | null;
  isPlaceholder?: boolean;
}) {
  const displayEvents = isPlaceholder ? PLACEHOLDER_EVENTS : (events ?? null);

  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Recent Events</span>
        {isPlaceholder && <span className="placeholder-tag">placeholder</span>}
      </div>
      {displayEvents === null || displayEvents.length === 0 ? (
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
              {displayEvents.map((e) => (
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

function RuntimeSection({
  runtime,
  lastUpdated,
}: {
  runtime: RuntimeStatus | null;
  lastUpdated: Date | null;
}) {
  const display = runtime ?? PLACEHOLDER_RUNTIME;

  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Runtime</span>
        <LastUpdatedStamp date={lastUpdated} />
      </div>
      <div className="runtime-grid">
        <div className="metric-card">
          <div className="metric-label">Last Cycle</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_cycle_status ?? '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Cycles / Hour</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.cycles_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Orders / Hour</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.orders_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Last Error</div>
          <div className={`metric-value ${display.last_error_message ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_error_message ?? (runtime ? 'none' : '—')}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Page component ─────────────────────────────────────────────────────────────

type ApiFailures = {
  health: boolean;
  risk: boolean;
  portfolio: boolean;
  orders: boolean;
  events: boolean;
  runtime: boolean;
};

export default function Overview() {
  const [health,    setHealth]    = useState<HealthStatus | null>(null);
  const [risk,      setRisk]      = useState<RiskStatus | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [orders,    setOrders]    = useState<OrderSummary[] | null>(null);
  const [events,    setEvents]    = useState<EventsSummary[] | null>(null);
  const [runtime,   setRuntime]   = useState<RuntimeStatus | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [failures,  setFailures]  = useState<ApiFailures>({
    health: false,
    risk: false,
    portfolio: false,
    orders: false,
    events: false,
    runtime: false,
  });

  const hasApiFailure = Object.values(failures).some(Boolean);

  const fetchAll = () => {
    getHealth()
      .then((data) => { setHealth(data); setFailures((f) => ({ ...f, health: false })); })
      .catch(() => setFailures((f) => ({ ...f, health: true })));

    getRiskStatus(500, 500)
      .then((data) => { setRisk(data); setFailures((f) => ({ ...f, risk: false })); })
      .catch(() => setFailures((f) => ({ ...f, risk: true })));

    getPortfolioStatus(500)
      .then((data) => { setPortfolio(data); setFailures((f) => ({ ...f, portfolio: false })); })
      .catch(() => setFailures((f) => ({ ...f, portfolio: true })));

    getRecentOrders()
      .then((r) => { setOrders(r.orders); setFailures((f) => ({ ...f, orders: false })); })
      .catch(() => setFailures((f) => ({ ...f, orders: true })));

    getRecentEvents()
      .then((r) => { setEvents(r.events); setFailures((f) => ({ ...f, events: false })); })
      .catch(() => setFailures((f) => ({ ...f, events: true })));

    getRuntimeStatus()
      .then((data) => { setRuntime(data); setFailures((f) => ({ ...f, runtime: false })); })
      .catch(() => setFailures((f) => ({ ...f, runtime: true })));

    setLastUpdated(new Date());
  };

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="page">
      <SafetyBanner />

      {hasApiFailure && <OfflineNotice />}

      <StatusStrip
        health={failures.health ? null : health}
        risk={failures.risk ? null : risk}
        healthFailed={failures.health}
        riskFailed={failures.risk}
      />

      <MetricsGrid
        portfolio={failures.portfolio ? null : portfolio}
        risk={failures.risk ? null : risk}
        riskFailed={failures.risk}
        portfolioFailed={failures.portfolio}
      />
      <PositionsSection positions={failures.portfolio ? null : (portfolio?.positions ?? null)} />
      <OrdersSection orders={failures.orders ? null : orders} />
      <EventsSection events={events} isPlaceholder={failures.events} />
      <RuntimeSection runtime={failures.runtime ? null : runtime} lastUpdated={lastUpdated} />
    </div>
  );
}
