import { useEffect, useState } from 'react';
import { getHealth, getRuntimeStatus, getMarketDataStatus, type HealthStatus, type RuntimeStatus, type MarketDataStatus } from '../api/client';

export default function Settings() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [marketData, setMarketData] = useState<MarketDataStatus | null>(null);

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
    </div>
  );
}
