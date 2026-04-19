import { useEffect, useState } from 'react';
import { getRecentOrders, type OrderSummary } from '../api/client';
import { fmtNum, fmtTime } from '../lib';

interface OrderAggregate {
  count1h: number;
  count24h: number;
  notional1h: number;
  notional24h: number;
}

export default function Orders() {
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const fetchOrders = () => {
    getRecentOrders()
      .then((r) => {
        setOrders(r.orders);
        setFailed(false);
      })
      .catch(() => {
        setFailed(true);
        setOrders([]);
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
          <span className="agg-label">Last 1h — Count</span>
          <span className="agg-value">{aggregates.count1h}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">Last 1h — Notional</span>
          <span className="agg-value">${fmtNum(aggregates.notional1h)}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">Last 24h — Count</span>
          <span className="agg-value">{aggregates.count24h}</span>
        </div>
        <div className="agg-item">
          <span className="agg-label">Last 24h — Notional</span>
          <span className="agg-value">${fmtNum(aggregates.notional24h)}</span>
        </div>
      </div>

      <div className="section">
        <div className="section-header">
          <span className="section-title">All Orders ({orders.length})</span>
          {failed && <span className="placeholder-tag">offline</span>}
        </div>
        {loading ? (
          <div className="empty-state">Loading…</div>
        ) : orders.length === 0 ? (
          <div className="empty-state">No orders</div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Status</th>
                  <th>Notional</th>
                  <th>Created</th>
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
