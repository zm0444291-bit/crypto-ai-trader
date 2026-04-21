import { useEffect, useState } from 'react';
import {
  getOrderLifecycleSummary,
  getRecentOrders,
  type OrderLifecycleSummary,
  type OrderSummary,
} from '../api/client';
import { fmtNum, fmtTime } from '../lib';

interface OrderAggregate {
  count1h: number;
  count24h: number;
  notional1h: number;
  notional24h: number;
}

export default function Orders() {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [lifecycle, setLifecycle] = useState<OrderLifecycleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [summaryFailed, setSummaryFailed] = useState(false);

  const fetchOrders = () => {
    Promise.allSettled([getRecentOrders(), getOrderLifecycleSummary()])
      .then(([ordersRes, summaryRes]) => {
        if (ordersRes.status === 'fulfilled') {
          setOrders(ordersRes.value.orders);
          setFailed(false);
        } else {
          setFailed(true);
          setOrders([]);
        }

        if (summaryRes.status === 'fulfilled') {
          setLifecycle(summaryRes.value);
          setSummaryFailed(false);
        } else {
          setSummaryFailed(true);
          setLifecycle(null);
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchOrders();
    const id = setInterval(fetchOrders, 30_000);
    return () => clearInterval(id);
  }, []);

  const aggregates: OrderAggregate = (() => {
    const now = Date.now();
    const oneHour = 60 * 60 * 1000;
    const dayAgo = now - 24 * oneHour;

    let count1h = 0, count24h = 0;
    let notional1h = 0, notional24h = 0;

    for (const o of orders) {
      const created = new Date(o.created_at).getTime();
      const notional = parseFloat(o.requested_notional_usdt) || 0;

      if (created >= dayAgo) {
        count24h++;
        notional24h += notional;
      }
      if (created >= now - oneHour) {
        count1h++;
        notional1h += notional;
      }
    }

    return { count1h, count24h, notional1h, notional24h };
  })();

  return (
    <div className="page">
      <div className="aggregate-bar">
        <div className="agg-item">
          <span className="agg-label">最近 1 小时 — 笔数</span>
          <span className="agg-value">{aggregates.count1h}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">最近 1 小时 — 名义金额</span>
          <span className="agg-value">${fmtNum(aggregates.notional1h)}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">最近 24 小时 — 笔数</span>
          <span className="agg-value">{aggregates.count24h}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">最近 24 小时 — 名义金额</span>
          <span className="agg-value">${fmtNum(aggregates.notional24h)}</span>
        </div>
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">订单生命周期监控</span>
          {summaryFailed && <span className="placeholder-tag">摘要离线</span>}
        </div>
        {lifecycle === null ? (
          <div className="empty-state">摘要不可用，保留订单明细。</div>
        ) : (
          <div className="aggregate-bar">
            <div className="agg-item">
              <span className="agg-label">{`最近 ${lifecycle.window_hours} 小时总单数`}</span>
              <span className="agg-value">{lifecycle.total_orders}</span>
            </div>
            <div className="agg-item">
              <span className="agg-label">PENDING_UNKNOWN</span>
              <span className="agg-value">{lifecycle.pending_unknown_count}</span>
            </div>
            <div className="agg-item">
              <span className="agg-label">FAILED</span>
              <span className="agg-value">{lifecycle.failed_count}</span>
            </div>
            <div className="agg-item">
              <span className="agg-label">REJECTED</span>
              <span className="agg-value">{lifecycle.rejected_count}</span>
            </div>
          </div>
        )}
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">全部订单（{orders.length}）</span>
          {failed && <span className="placeholder-tag">离线</span>}
        </div>
        {loading ? (
          <div className="empty-state">加载中…</div>
        ) : orders.length === 0 ? (
          <div className="empty-state">暂无订单</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>交易对</th>
                  <th>方向</th>
                  <th>状态</th>
                  <th>名义金额</th>
                  <th>创建时间</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td>{o.symbol}</td>
                    <td className={o.side === 'BUY' ? 'side-buy' : 'side-sell'}>{o.side}</td>
                    <td>{o.status}</td>
                    <td>${fmtNum(o.requested_notional_usdt)}</td>
                    <td>{fmtTime(o.created_at)}</td>
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
