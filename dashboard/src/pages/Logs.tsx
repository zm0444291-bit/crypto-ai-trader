import { useEffect, useState } from 'react';
import { getRecentEventsFiltered, type EventsSummary } from '../api/client';
import { fmtTime, severityBadge } from '../lib';

const SEVERITIES = ['info', 'warning', 'error', 'success'] as const;
const COMPONENTS = ['runtime', 'ingestion', 'trading', 'supervisor', 'risk'] as const;

export default function Logs() {
  const [events, setEvents] = useState<EventsSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [severity, setSeverity] = useState<string>('');
  const [component, setComponent] = useState<string>('');

  const fetchLogs = () => {
    const opts: Parameters<typeof getRecentEventsFiltered>[0] = { limit: 100 };
    if (severity) opts.severity = severity;
    if (component) opts.component = component;

    getRecentEventsFiltered(opts)
      .then((r) => { setEvents(r.events); setFailed(false); })
      .catch(() => { setFailed(true); setEvents([]); })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, 15_000);
    return () => clearInterval(id);
  }, [severity, component]);

  return (
    <div className="page">
      <div className="filter-bar">
        <select
          className="filter-select"
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
        >
          <option value="">All Severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={component}
          onChange={(e) => setComponent(e.target.value)}
        >
          <option value="">All Components</option>
          {COMPONENTS.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">Events ({events.length})</span>
          {failed && <span className="placeholder-tag">offline</span>}
        </div>
        {loading ? (
          <div className="empty-state">Loading…</div>
        ) : events.length === 0 ? (
          <div className="empty-state">No events match the current filters</div>
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
    </div>
  );
}
