import { useCallback, useEffect, useState } from 'react';
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
  type PositionSummary,
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
  positions: [] as PositionSummary[],
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
  supervisor_alive: null,
  ingestion_thread_alive: null,
  trading_thread_alive: null,
  uptime_seconds: null,
  last_heartbeat_time: null,
  last_component_error: null,
  heartbeat_stale_alerting: false,
  last_recovered_time: null,
  restart_attempts_ingestion_last_hour: 0,
  restart_attempts_trading_last_hour: 0,
  restart_exhausted_ingestion: false,
  restart_exhausted_trading: false,
  last_restart_time: null,
  trade_mode: 'paper_auto',
  live_trading_lock_enabled: false,
  execution_route_effective: 'paper',
  mode_transition_guard: null,
  shadow_executions_last_hour: 0,
  last_shadow_time: null,
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

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function ExecutionStatusBanner({ runtime }: { runtime: RuntimeStatus | null }) {
  if (!runtime) return null;

  const { trade_mode, live_trading_lock_enabled, execution_route_effective, mode_transition_guard } = runtime;

  let label: string;
  let labelClass: string;

  // Guard blocked — always show first, before any mode-specific text
  if (mode_transition_guard && mode_transition_guard.startsWith('blocked:')) {
    const reason = mode_transition_guard.replace('blocked: ', '');
    label = `Mode transition blocked — see Settings > Execution Control`;
    labelClass = 'exec-banner-blocked';
    void reason; // stored in runtime.mode_transition_guard for Settings to surface
  } else if (live_trading_lock_enabled) {
    label = 'Live execution blocked — lock is active';
    labelClass = 'exec-banner-locked';
  } else if (trade_mode === 'paper_auto' || trade_mode === 'paper') {
    label = 'Paper execution active';
    labelClass = 'exec-banner-paper';
  } else if (trade_mode === 'dry_run') {
    label = 'Dry-run mode — no real orders';
    labelClass = 'exec-banner-dryrun';
  } else if (trade_mode === 'live_shadow') {
    label = 'Shadow mode — live prices, no execution';
    labelClass = 'exec-banner-shadow';
  } else if (trade_mode === 'live_small_auto') {
    label = 'Live execution active';
    labelClass = 'exec-banner-live';
  } else {
    label = `Mode: ${trade_mode}`;
    labelClass = 'exec-banner-default';
  }

  return (
    <div className={`exec-status-banner ${labelClass}`}>
      <span className="exec-status-dot" />
      <span className="exec-status-label">{label}</span>
      <span className="exec-status-route">route&nbsp;{execution_route_effective}</span>
    </div>
  );
}

// ── Status helpers ────────────────────────────────────────────────────────────

/** Dot class for the heartbeat card — also reflects heartbeat_stale_alerting. */
function heartbeatDotClass(alerting: boolean, supervisorAlive: boolean | null): string {
  if (alerting) return 'dot-stale';
  if (supervisorAlive === false) return 'dot-degraded';
  if (supervisorAlive === true) return 'dot-normal';
  return 'dot-disabled';
}

/** Human-readable label for the heartbeat / heartbeat-alerting card. */
function heartbeatLabel(alerting: boolean, lastHeartbeat: string | null): { label: string; hint: string | null } {
  if (alerting) {
    return {
      label: 'STALE',
      hint: lastHeartbeat ? `Last seen ${fmtTime(lastHeartbeat)} — restart trader` : 'No heartbeat — restart trader',
    };
  }
  return { label: 'OK', hint: null };
}

/** Human-readable label for the restart-exhausted card. */
function restartExhaustedLabel(ingestion: boolean, trading: boolean): string {
  if (ingestion && trading) return 'BOTH EXHAUSTED — check connections';
  if (ingestion) return 'INGESTION EXHAUSTED — check data source';
  if (trading) return 'TRADING EXHAUSTED — check exchange API';
  return '—';
}

function RuntimeSection({
  runtime,
  lastUpdated,
}: {
  runtime: RuntimeStatus | null;
  lastUpdated: Date | null;
}) {
  const display = runtime ?? PLACEHOLDER_RUNTIME;

  const hbDot = heartbeatDotClass(display.heartbeat_stale_alerting, display.supervisor_alive);
  const hbInfo = heartbeatLabel(display.heartbeat_stale_alerting, display.last_heartbeat_time);

  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">Runtime</span>
        <LastUpdatedStamp date={lastUpdated} />
      </div>
      <ExecutionStatusBanner runtime={runtime} />
      <div className="runtime-grid">
        <div className="metric-card">
          <div className="metric-label">Heartbeat</div>
          <div className="metric-value">
            <span className={`dot ${hbDot}`} />
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Uptime</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.uptime_seconds !== null ? formatUptime(display.uptime_seconds) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Last Heartbeat</div>
          <div className={`metric-value ${display.heartbeat_stale_alerting ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_heartbeat_time ? fmtTime(display.last_heartbeat_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Heartbeat Alerting</div>
          <div className={`metric-value ${display.heartbeat_stale_alerting ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.heartbeat_stale_alerting
              ? <span title={hbInfo.hint ?? undefined}>{hbInfo.label}</span>
              : (runtime ? hbInfo.label : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Heartbeat Recovered</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_recovered_time ? fmtTime(display.last_recovered_time) : '—'}
          </div>
        </div>
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
          <div className="metric-label">Shadow / Hour</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.shadow_executions_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Last Shadow</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_shadow_time ? fmtTime(display.last_shadow_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Last Error</div>
          <div className={`metric-value ${display.last_error_message ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_error_message ?? (runtime ? 'none' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Component Error</div>
          <div className={`metric-value ${display.last_component_error ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_component_error ?? (runtime ? 'none' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Trade Mode</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.trade_mode}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Live Lock</div>
          <div className={`metric-value ${display.live_trading_lock_enabled ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.live_trading_lock_enabled ? 'ON' : 'OFF'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Execution Route</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.execution_route_effective}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Mode Guard</div>
          <div className={`metric-value ${display.mode_transition_guard && display.mode_transition_guard.startsWith('blocked') ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.mode_transition_guard ?? (runtime ? '—' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Restart I/T (1h)</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.restart_attempts_ingestion_last_hour}/{display.restart_attempts_trading_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Restart Exhausted</div>
          <div className={`metric-value ${(display.restart_exhausted_ingestion || display.restart_exhausted_trading) ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {restartExhaustedLabel(display.restart_exhausted_ingestion, display.restart_exhausted_trading)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Last Restart</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_restart_time ? fmtTime(display.last_restart_time) : '—'}
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

  const fetchAll = useCallback(() => {
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
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, [fetchAll]);

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
