import { useEffect, useRef, useState } from 'react';
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

  // Keep latest filter values in a ref so the polling interval stays stable
  const filterRef = useRef({ severity: '', component: '' });

  const fetchLogs = () => {
    const { severity: sev, component: comp } = filterRef.current;
    const opts: Parameters<typeof getRecentEventsFiltered>[0] = { limit: 100 };
    if (sev) opts.severity = sev;
    if (comp) opts.component = comp;
    getRecentEventsFiltered(opts)
      .then((r) => { setEvents(r.events); setFailed(false); })
      .catch(() => { setFailed(true); setEvents([]); })
      .finally(() => setLoading(false));
  };

  // Stable polling interval — does not restart when filters change
  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, 15_000);
    return () => clearInterval(id);
  }, []);

  // Keep ref in sync with filter state without restarting the polling interval
  useEffect(() => {
    filterRef.current = { severity, component };
  }, [severity, component]);

  return (
    <div className="page">
      <div className="filter-bar">
        <select
          className="filter-select"
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
        >
          <option value="">全部级别</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          className="filter-select"
          value={component}
          onChange={(e) => setComponent(e.target.value)}
        >
          <option value="">全部组件</option>
          {COMPONENTS.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">事件（{events.length}）</span>
          {failed && <span className="placeholder-tag">离线</span>}
        </div>
        {loading ? (
          <div className="empty-state">加载中…</div>
        ) : events.length === 0 ? (
          <div className="empty-state">没有匹配当前筛选条件的事件</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>级别</th>
                  <th>组件</th>
                  <th>类型</th>
                  <th>消息</th>
                  <th>时间</th>
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
