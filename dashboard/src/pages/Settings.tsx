import { useEffect, useState } from 'react';
import {
  getHealth,
  getRuntimeStatus,
  getMarketDataStatus,
  getControlPlane,
  setControlPlaneMode,
  setLiveLock,
  type HealthStatus,
  type RuntimeStatus,
  type MarketDataStatus,
  type ControlPlaneResponse,
  type TradeMode,
  type ModeChangeResponse,
  type LiveLockChangeResponse,
} from '../api/client';

const PLACEHOLDER_CONTROL: ControlPlaneResponse = {
  trade_mode: 'paper_auto',
  lock_enabled: false,
  lock_reason: null,
  execution_route: 'paper',
  transition_guard_to_live_small_auto: '—',
};

const TRADE_MODES: TradeMode[] = ['paused', 'paper_auto', 'live_shadow', 'live_small_auto'];

function FeedbackBanner({
  success,
  message,
}: {
  success: boolean;
  message: string;
}) {
  return (
    <div className={`feedback-banner ${success ? 'feedback-success' : 'feedback-error'}`}>
      <span>{success ? '✓' : '✗'}</span>
      <span>{message}</span>
    </div>
  );
}

export default function Settings() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [marketData, setMarketData] = useState<MarketDataStatus | null>(null);
  const [controlPlane, setControlPlane] = useState<ControlPlaneResponse | null>(null);
  const [controlPlaneFailed, setControlPlaneFailed] = useState(false);

  const [modeValue, setModeValue] = useState<string>('paper_auto');
  const [allowLiveUnlock, setAllowLiveUnlock] = useState(false);
  const [modeReason, setModeReason] = useState('');
  const [modeLoading, setModeLoading] = useState(false);
  const [modeFeedback, setModeFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const [lockEnabled, setLockEnabled] = useState(false);
  const [lockReason, setLockReason] = useState('');
  const [lockLoading, setLockLoading] = useState(false);
  const [lockFeedback, setLockFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const refreshControlPlane = () => {
    getControlPlane()
      .then((data) => { setControlPlane(data); setControlPlaneFailed(false); })
      .catch(() => setControlPlaneFailed(true));
    getRuntimeStatus()
      .then(setRuntime)
      .catch(() => {});
  };

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

  const handleApplyMode = async () => {
    setModeLoading(true);
    setModeFeedback(null);
    try {
      const res: ModeChangeResponse = await setControlPlaneMode(
        modeValue as TradeMode,
        allowLiveUnlock,
        modeReason || undefined,
      );
      setModeFeedback({ success: res.success, message: res.reason });
      if (res.success) {
        setModeReason('');
        setAllowLiveUnlock(false);
        refreshControlPlane();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unexpected error';
      setModeFeedback({ success: false, message: msg });
    } finally {
      setModeLoading(false);
    }
  };

  const handleApplyLock = async () => {
    setLockLoading(true);
    setLockFeedback(null);
    try {
      const res: LiveLockChangeResponse = await setLiveLock(
        lockEnabled,
        lockReason || undefined,
      );
      setLockFeedback({ success: res.success, message: res.reason });
      if (res.success) {
        setLockReason('');
        refreshControlPlane();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unexpected error';
      setLockFeedback({ success: false, message: msg });
    } finally {
      setLockLoading(false);
    }
  };

  const isBlocked = (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto.startsWith('blocked:');
  const guardReason = (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto;

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

      {isBlocked && (
        <div className="guard-warning-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <span>Transition guard active — {guardReason}</span>
        </div>
      )}

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

      <div className="settings-section">
        <div className="settings-title">Execution Control Actions</div>

        <div className="control-action-group">
          <div className="control-action-label">Mode</div>
          <div className="control-action-row">
            <select
              className="filter-select"
              value={modeValue}
              onChange={(e) => setModeValue(e.target.value)}
            >
              {TRADE_MODES.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={allowLiveUnlock}
                onChange={(e) => setAllowLiveUnlock(e.target.checked)}
              />
              <span>allow_live_unlock</span>
            </label>
          </div>
          <input
            className="control-input"
            type="text"
            placeholder="reason (optional)"
            value={modeReason}
            onChange={(e) => setModeReason(e.target.value)}
          />
          {modeFeedback && (
            <FeedbackBanner success={modeFeedback.success} message={modeFeedback.message} />
          )}
          <button
            className="control-btn"
            onClick={handleApplyMode}
            disabled={modeLoading}
          >
            {modeLoading ? 'Applying…' : 'Apply Mode'}
          </button>
        </div>

        <div className="control-action-group">
          <div className="control-action-label">Live Lock</div>
          <div className="control-action-row">
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={lockEnabled}
                onChange={(e) => setLockEnabled(e.target.checked)}
              />
              <span>enabled</span>
            </label>
          </div>
          <input
            className="control-input"
            type="text"
            placeholder="reason (optional)"
            value={lockReason}
            onChange={(e) => setLockReason(e.target.value)}
          />
          {lockFeedback && (
            <FeedbackBanner success={lockFeedback.success} message={lockFeedback.message} />
          )}
          <button
            className="control-btn"
            onClick={handleApplyLock}
            disabled={lockLoading}
          >
            {lockLoading ? 'Applying…' : 'Apply Lock'}
          </button>
        </div>
      </div>
    </div>
  );
}
