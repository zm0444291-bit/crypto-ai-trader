import { useEffect, useState } from 'react';
import { getRecentEvents, type EventsSummary } from '../api/client';
import { fmtTime, severityBadge } from '../lib';

const SIGNAL_TYPES = ['cycle_candidate', 'cycle_no_signal', 'cycle_rejected', 'cycle_executed'] as const;
type SignalType = typeof SIGNAL_TYPES[number];

interface SignalEvent extends EventsSummary {
  decision?: string;
  reason?: string;
}

const PLACEHOLDER_SIGNALS: SignalEvent[] = [
  {
    id: -1,
    event_type: 'cycle_candidate',
    severity: 'info',
    component: 'trading',
    message: '后端离线，显示占位数据',
    created_at: new Date().toISOString(),
    decision: '观望',
    reason: '无信号',
  },
];

function signalTypeLabel(eventType: string): string {
  switch (eventType) {
    case 'cycle_candidate':
      return '候选';
    case 'cycle_no_signal':
      return '无信号';
    case 'cycle_rejected':
      return '拒绝';
    case 'cycle_executed':
      return '已执行';
    default:
      return eventType;
  }
}

export default function Signals() {
  const [events, setEvents] = useState<SignalEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const fetchSignals = () => {
    getRecentEvents({ limit: 200 })
      .then((r) => {
        const filtered = r.events.filter((e): e is SignalEvent =>
          SIGNAL_TYPES.includes(e.event_type as SignalType)
        );
        setEvents(filtered);
        setFailed(false);
      })
      .catch(() => {
        setFailed(true);
        setEvents(PLACEHOLDER_SIGNALS);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSignals();
    const id = setInterval(fetchSignals, 30_000);
    return () => clearInterval(id);
  }, []);

  const counts: Record<SignalType, number> = {
    cycle_candidate: 0,
    cycle_no_signal: 0,
    cycle_rejected: 0,
    cycle_executed: 0,
  };
  for (const e of events) {
    if (e.event_type in counts) {
      counts[e.event_type as SignalType]++;
    }
  }

  const signalClass = (eventType: string): string => {
    switch (eventType) {
      case 'cycle_candidate':   return 'signal-present';
      case 'cycle_no_signal':   return 'signal-no-signal';
      case 'cycle_rejected':    return 'signal-rejected';
      case 'cycle_executed':    return 'signal-executed';
      default:                  return '';
    }
  };

  return (
    <div className="page">
      <div className="section">
        <div className="section-header">
          <span className="section-title">信号统计</span>
        </div>
        <div className="aggregate-bar">
          {SIGNAL_TYPES.map((type) => (
            <div key={type} className="agg-item">
              <span className="agg-label">{signalTypeLabel(type)}</span>
              <span className={`agg-value ${signalClass(type)}`}>{counts[type]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">最近候选事件</span>
          {failed && <span className="placeholder-tag">离线</span>}
        </div>
        {loading ? (
          <div className="empty-state">加载中…</div>
        ) : events.length === 0 ? (
          <div className="empty-state">暂无信号事件</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>交易对</th>
                  <th>类型</th>
                  <th>决策</th>
                  <th>原因</th>
                  <th>级别</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, 100).map((e) => {
                  const msg = e.message || '';
                  const symbolMatch = msg.match(/\[([A-Z]{2,10}(?:USDT|USD|BTC|ETH))\]/);
                  const symbol = symbolMatch ? symbolMatch[1] : '—';
                  const decisionMatch = msg.match(/decision[:\s]+(\w+)/i);
                  const decision = decisionMatch ? decisionMatch[1] : e.decision ?? '—';
                  const reasonMatch = msg.match(/reason[:\s]+(.+)/i);
                  const reason = reasonMatch ? reasonMatch[1].trim() : e.reason ?? '—';

                  return (
                    <tr key={e.id}>
                      <td>{symbol}</td>
                      <td className={signalClass(e.event_type)}>{signalTypeLabel(e.event_type)}</td>
                      <td className={signalClass(e.event_type)}>{decision}</td>
                      <td>{reason}</td>
                      <td><span className={severityBadge(e.severity)}>{e.severity}</span></td>
                      <td>{fmtTime(e.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
