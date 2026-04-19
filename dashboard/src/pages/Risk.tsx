import { useCallback, useEffect, useState } from 'react';
import { getRiskStatus, getRecentEvents, type EventsSummary, type RiskStatus } from '../api/client';
import { severityBadge, fmtNum, fmtTime } from '../lib';

function eventReason(e: EventsSummary): string | null {
  if (!e.context) return null;
  const ctx = e.context as Record<string, unknown>;
  if (e.event_type === 'execution_gate_blocked') {
    const reason = ctx.reason ?? ctx.block_reason;
    return reason ? String(reason) : null;
  }
  if (e.event_type === 'risk_rejected') {
    const reasons = ctx.reject_reasons;
    if (Array.isArray(reasons) && reasons.length > 0) return reasons.join(', ');
    return null;
  }
  if (e.event_type === 'supervisor_component_error') {
    return (ctx.error as string) ?? null;
  }
  return null;
}

function EventRow({ e }: { e: EventsSummary }) {
  const reason = eventReason(e);
  return (
    <tr>
      <td><span className={severityBadge(e.severity)}>{e.severity}</span></td>
      <td>{e.component}</td>
      <td>{e.message}{reason ? <span className="event-reason"> — {reason}</span> : null}</td>
      <td>{fmtTime(e.created_at)}</td>
    </tr>
  );
}

function EventTable({ events, empty }: { events: EventsSummary[]; empty: string }) {
  if (events.length === 0) return <div className="empty-state">{empty}</div>;
  return (
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
          {events.map((e) => <EventRow key={e.id} e={e} />)}
        </tbody>
      </table>
    </div>
  );
}

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
const PLACEHOLDER_GATE: EventsSummary[] = [];
const PLACEHOLDER_SUPERVISOR: EventsSummary[] = [];

export default function Risk() {
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [rejects, setRejects] = useState<EventsSummary[]>([]);
  const [gateBlocks, setGateBlocks] = useState<EventsSummary[]>([]);
  const [supervisorErrors, setSupervisorErrors] = useState<EventsSummary[]>([]);
  const [riskFailed, setRiskFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchRisk = useCallback(() => {
    getRiskStatus(500, 500)
      .then((data) => { setRisk(data); setRiskFailed(false); })
      .catch(() => { setRiskFailed(true); setRisk(PLACEHOLDER_RISK); })
      .finally(() => setLoading(false));
  }, []);

  const fetchRejects = useCallback(() => {
    getRecentEvents({ limit: 20, event_type: 'risk_rejected' })
      .then((r) => setRejects(r.events))
      .catch(() => setRejects(PLACEHOLDER_REJECTS));
  }, []);

  const fetchGateBlocks = useCallback(() => {
    getRecentEvents({ limit: 10, event_type: 'execution_gate_blocked' })
      .then((r) => setGateBlocks(r.events))
      .catch(() => setGateBlocks(PLACEHOLDER_GATE));
  }, []);

  const fetchSupervisorErrors = useCallback(() => {
    getRecentEvents({ limit: 10, event_type: 'supervisor_component_error' })
      .then((r) => setSupervisorErrors(r.events))
      .catch(() => setSupervisorErrors(PLACEHOLDER_SUPERVISOR));
  }, []);

  useEffect(() => {
    fetchRisk();
    fetchRejects();
    fetchGateBlocks();
    fetchSupervisorErrors();
    const id = setInterval(() => { fetchRisk(); fetchRejects(); fetchGateBlocks(); fetchSupervisorErrors(); }, 30_000);
    return () => clearInterval(id);
  }, [fetchRisk, fetchRejects, fetchGateBlocks, fetchSupervisorErrors]);

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
            <EventTable events={rejects} empty="No risk rejections" />
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">Execution Gate Blocks</span>
            </div>
            <EventTable events={gateBlocks} empty="No execution gate blocks" />
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">Supervisor Component Errors</span>
            </div>
            <EventTable events={supervisorErrors} empty="No supervisor errors" />
          </div>
        </>
      )}
    </div>
  );
}
