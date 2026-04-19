import { useEffect, useState } from 'react';
import { getRiskStatus, getRecentEvents, type RiskStatus, type EventsSummary } from '../api/client';
import { severityBadge, fmtNum, fmtTime } from '../lib';

const PLACEHOLDER_RISK: RiskStatus = {
  day_start_equity: '500',
  current_equity: '500',
  risk_profile: { name: 'small_balanced' },
  risk_state: 'normal',
  daily_pnl_pct: '0',
  max_trade_risk_usdt: '7.5',
  reason: 'placeholder — backend offline',
};

const PLACEHOLDER_REJECTS: EventsSummary[] = [];

export default function Risk() {
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [rejects, setRejects] = useState<EventsSummary[]>([]);
  const [riskFailed, setRiskFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchRisk = () => {
    getRiskStatus(500, 500)
      .then((data) => { setRisk(data); setRiskFailed(false); })
      .catch(() => { setRiskFailed(true); setRisk(PLACEHOLDER_RISK); })
      .finally(() => setLoading(false));
  };

  const fetchRejects = () => {
    getRecentEvents({ limit: 20 })
      .then((r) => setRejects(r.events.filter((e) => e.event_type === 'risk_reject')))
      .catch(() => setRejects(PLACEHOLDER_REJECTS));
  };

  useEffect(() => {
    fetchRisk();
    fetchRejects();
    const id = setInterval(() => { fetchRisk(); fetchRejects(); }, 30_000);
    return () => clearInterval(id);
  }, []);

  const displayRisk = riskFailed ? PLACEHOLDER_RISK : risk;

  const stateColor = (state: string): string => {
    switch (state) {
      case 'normal':            return 'var(--positive)';
      case 'degraded':          return 'var(--warning)';
      case 'no_new_positions': return 'var(--danger)';
      case 'global_pause':      return 'var(--danger)';
      case 'emergency_stop':   return 'var(--danger)';
      default:                  return 'var(--text-muted)';
    }
  };

  return (
    <div className="page">
      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : (
        <>
          <div className="section">
            <div className="section-header">
              <span className="section-title">Current Risk State</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: displayRisk ? stateColor(displayRisk.risk_state) : 'var(--text-muted)',
                  flexShrink: 0,
                }}
              />
              <span style={{ fontFamily: 'var(--mono)', fontWeight: 600, fontSize: '0.9rem' }}>
                {displayRisk?.risk_state ?? 'unknown'}
              </span>
            </div>
            {displayRisk?.reason && displayRisk.reason !== 'placeholder — backend offline' && (
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                Reason: {displayRisk.reason}
              </div>
            )}
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">Risk Profile</span>
            </div>
            <div className="thresholds-grid">
              <div className="threshold-card">
                <div className="thresh-name">Profile</div>
                <div className="thresh-pct">{displayRisk?.risk_profile.name ?? '—'}</div>
              </div>
              <div className="threshold-card">
                <div className="thresh-name">Daily PnL %</div>
                <div className="thresh-pct" style={{
                  color: displayRisk && parseFloat(displayRisk.daily_pnl_pct) >= 0
                    ? 'var(--positive)' : 'var(--negative)'
                }}>
                  {displayRisk ? `${parseFloat(displayRisk.daily_pnl_pct) >= 0 ? '+' : ''}${displayRisk.daily_pnl_pct}%` : '—'}
                </div>
              </div>
              <div className="threshold-card">
                <div className="thresh-name">Max Trade Risk</div>
                <div className="thresh-pct">${fmtNum(displayRisk?.max_trade_risk_usdt ?? '0')}</div>
              </div>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">Recent Risk Rejections</span>
            </div>
            {rejects.length === 0 ? (
              <div className="empty-state">No risk rejections</div>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>Component</th>
                      <th>Message</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rejects.map((e) => (
                      <tr key={e.id}>
                        <td><span className={severityBadge(e.severity)}>{e.severity}</span></td>
                        <td>{e.component}</td>
                        <td>{e.message}</td>
                        <td>{fmtTime(e.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
