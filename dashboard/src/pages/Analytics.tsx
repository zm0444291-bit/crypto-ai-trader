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
        <div className="empty-state">Loading…</div>
      ) : (
        <>
          <div className="analytics-metrics">
            <div className="metric-card">
              <div className="metric-label">Current Equity</div>
              <div className="metric-value">${fmtNum(display?.current_equity_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Day Start Equity</div>
              <div className="metric-value">${fmtNum(display?.day_start_equity_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Daily PnL</div>
              <div className={`metric-value ${(parseFloat(display?.daily_pnl_usdt ?? '0') || 0) >= 0 ? 'positive' : 'negative'}`}>
                {display ? (
                  parseFloat(display.daily_pnl_usdt) >= 0
                    ? `+$${fmtNum(display.daily_pnl_usdt)}`
                    : `-$${fmtNum(Math.abs(parseFloat(display.daily_pnl_usdt)))}`
                ) : '—'}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Daily PnL %</div>
              <div className={`metric-value ${(parseFloat(display?.daily_pnl_pct ?? '0') || 0) >= 0 ? 'positive' : 'negative'}`}>
                {fmtPct(display?.daily_pnl_pct ?? '0')}
              </div>
            </div>
          </div>

          <div className="analytics-metrics">
            <div className="metric-card">
              <div className="metric-label">Total Trades</div>
              <div className="metric-value">{display?.total_trades ?? 0}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Win Rate</div>
              <div className="metric-value">{fmtPct(display?.win_rate_pct ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Avg Win</div>
              <div className="metric-value positive">${fmtNum(display?.avg_win_usdt ?? '0')}</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Avg Loss</div>
              <div className="metric-value negative">${fmtNum(display?.avg_loss_usdt ?? '0')}</div>
            </div>
          </div>

          <div className="section">
            <div className="section-header">
              <span className="section-title">Win / Loss Breakdown</span>
            </div>
            <div className="analytics-metrics">
              <div className="metric-card">
                <div className="metric-label">Winning Trades</div>
                <div className="metric-value positive">{display?.winning_trades ?? 0}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Losing Trades</div>
                <div className="metric-value negative">{display?.losing_trades ?? 0}</div>
              </div>
            </div>
          </div>

          {display && display.equity_snapshots.length > 0 && (
            <div className="section">
              <div className="section-header">
                <span className="section-title">Equity Snapshots</span>
              </div>
              <div className="snapshot-list">
                {display.equity_snapshots.map((s, i) => {
                  const pnl = parseFloat(s.equity_usdt) - (display.day_start_equity_usdt ? parseFloat(display.day_start_equity_usdt) : 0);
                  return (
                    <div key={i} className={`snapshot-row ${pnl >= 0 ? 'positive' : 'negative'}`}>
                      <span className="snapshot-date">
                        {new Date(s.timestamp).toLocaleString('en-US', {
                          month: 'short', day: 'numeric',
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
            <div className="empty-state">Backend offline — showing placeholder data</div>
          )}
        </>
      )}
    </div>
  );
}
