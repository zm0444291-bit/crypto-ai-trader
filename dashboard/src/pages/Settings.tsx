import { useEffect, useState } from 'react';
import { getHealth, getRuntimeStatus, getMarketDataStatus, getControlPlane, type HealthStatus, type RuntimeStatus, type MarketDataStatus, type ControlPlaneResponse } from '../api/client';

const PLACEHOLDER_CONTROL: ControlPlaneResponse = {
  trade_mode: 'paper_auto',
  lock_enabled: false,
  lock_reason: null,
  execution_route: 'paper',
  transition_guard_to_live_small_auto: '—',
};

export default function Settings() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [marketData, setMarketData] = useState<MarketDataStatus | null>(null);
  const [controlPlane, setControlPlane] = useState<ControlPlaneResponse | null>(null);
  const [controlPlaneFailed, setControlPlaneFailed] = useState(false);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => {});
    getRuntimeStatus()
      .then(setRuntime)
      .catch(() => {});
    getMarketDataStatus()
      .then(setMarketData)
      .catch(() => {});
    getControlPlane()
      .then((data) => { setControlPlane(data); setControlPlaneFailed(false); })
      .catch(() => setControlPlaneFailed(true));
  }, []);

  return (
    <div className="page">
      <div className="safety-notice">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }} aria-hidden="true">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>
          This dashboard operates in paper-only mode. No real funds are used. Live trading requires explicit unlock in a future milestone.
        </span>
      </div>

      <div className="settings-section">
        <div className="settings-title">System Info</div>
        <div className="settings-row">
          <span className="row-label">Mode</span>
          <span className="row-value">{health?.trade_mode ?? '—'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Live Trading Enabled</span>
          <span className="row-value">{health?.live_trading_enabled ? 'Yes' : 'No'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Last Cycle</span>
          <span className="row-value">{runtime?.last_cycle_status ?? '—'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Cycles / Hour</span>
          <span className="row-value">{runtime?.cycles_last_hour ?? '—'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Orders / Hour</span>
          <span className="row-value">{runtime?.orders_last_hour ?? '—'}</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">Market Data</div>
        <div className="settings-row">
          <span className="row-label">Connected</span>
          <span className="row-value">{marketData?.connected ? 'Yes' : 'No'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Symbols</span>
          <span className="row-value">{(marketData?.symbols ?? []).join(', ') || '—'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">Timeframes</span>
          <span className="row-value">{(marketData?.timeframes ?? []).join(', ') || '—'}</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">Database</div>
        <div className="settings-row">
          <span className="row-label">Location</span>
          <span className="row-value">data/crypto_ai_trader.sqlite3</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">Execution Control Plane</div>
        <div className="settings-row">
          <span className="row-label">Lock Enabled</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).lock_enabled
                ? 'Yes'
                : 'No'}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">Lock Reason</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : ((controlPlane ?? PLACEHOLDER_CONTROL).lock_reason ?? '—')}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">Execution Route</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).execution_route}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">Transition Guard</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto}
          </span>
        </div>
      </div>
    </div>
  );
}
