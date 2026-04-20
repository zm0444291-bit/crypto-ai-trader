import { useEffect, useState } from 'react';
import { getAnalyticsSummary, type AnalyticsSummary } from '../api/client';
import { fmtNum, fmtPct } from '../lib';

const PLACEHOLDER_ANALYTICS: AnalyticsSummary = {
  current_equity_usdt: '500',
  day_start_equity_usdt: '500',
  daily_pnl_usdt: '0',
  daily_pnl_pct: '0',
  total_trades: 0,
  winning_trades: 0,
  losing_trades: 0,
  win_rate_pct: '0',
  avg_win_usdt: '0',
  avg_loss_usdt: '0',
  equity_snapshots: [],
  daily_pnl_history: [],
};

export default function Analytics() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const fetchAnalytics = () => {
    getAnalyticsSummary()
      .then((r) => { setData(r); setFailed(false); })
      .catch(() => { setFailed(true); setData(PLACEHOLDER_ANALYTICS); })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchAnalytics();
    const id = setInterval(fetchAnalytics, 60_000);
    return () => clearInterval(id);
  }, []);

  const display = failed ? PLACEHOLDER_ANALYTICS : data;

  return (
    <div className="page">
      {loading ? (
        <div className="empty-state">加载中…</div>
      ) : (
        <>
          <div className="analytics-metrics">
            <div className="metric-card">
              <div className="metric-label">当前权益</div>
              <div className="metric-value">${fmtNum(display?.current_equity_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">日初权益</div>
              <div className="metric-value">${fmtNum(display?.day_start_equity_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">当日盈亏</div>
              <div className={`metric-value ${(parseFloat(display?.daily_pnl_usdt ?? '0') || 0) >= 0 ? 'positive' : 'negative'}`}>
                {display ? (
                  parseFloat(display.daily_pnl_usdt || '0') >= 0
                    ? `+$${fmtNum(display.daily_pnl_usdt)}`
                    : `-$${fmtNum(Math.abs(parseFloat(display.daily_pnl_usdt || '0')))}`
                ) : '—'}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">当日盈亏 %</div>
              <div className={`metric-value ${(parseFloat(display?.daily_pnl_pct ?? '0') || 0) >= 0 ? 'positive' : 'negative'}`}>
                {fmtPct(display?.daily_pnl_pct ?? '0')}
              </div>
            </div>
          </div>

          <div className="analytics-metrics">
            <div className="metric-card">
              <div className="metric-label">总交易数</div>
              <div className="metric-value">{display?.total_trades ?? 0}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">胜率</div>
              <div className="metric-value">{fmtPct(display?.win_rate_pct ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">平均盈利</div>
              <div className="metric-value positive">${fmtNum(display?.avg_win_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">平均亏损</div>
              <div className="metric-value negative">${fmtNum(display?.avg_loss_usdt ?? '0')}</div>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">盈亏拆分</span>
            </div>
            <div className="analytics-metrics">
              <div className="metric-card">
                <div className="metric-label">盈利笔数</div>
                <div className="metric-value positive">{display?.winning_trades ?? 0}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">亏损笔数</div>
                <div className="metric-value negative">{display?.losing_trades ?? 0}</div>
              </div>
            </div>
          </div>

          {display && display.equity_snapshots.length > 0 && (
            <div className="section">
              <div className="section-header">
                <span className="section-title">权益快照</span>
              </div>
              <div className="snapshot-list">
                {display.equity_snapshots.map((s, i) => {
                  const baseEquity = parseFloat(display.day_start_equity_usdt || '0');
                  const pnl = parseFloat(s.equity_usdt) - baseEquity;
                  return (
                    <div key={i} className={`snapshot-row ${pnl >= 0 ? 'positive' : 'negative'}`}>
                      <span className="snapshot-date">
                        {new Date(s.timestamp).toLocaleString('zh-CN', {
                          month: '2-digit', day: '2-digit',
                          hour: '2-digit', minute: '2-digit', hour12: false,
                        })}
                      </span>
                      <span className="snapshot-equity">${fmtNum(s.equity_usdt)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {failed && (
            <div className="empty-state">后端离线，显示占位数据</div>
          )}
        </>
      )}
    </div>
  );
}
