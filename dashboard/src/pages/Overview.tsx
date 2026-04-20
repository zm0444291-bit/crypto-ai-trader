import { useCallback, useEffect, useState } from 'react';
import {
  getHealth,
  getRiskStatus,
  getPortfolioStatus,
  getRecentOrders,
  getRecentEvents,
  getRuntimeStatus,
  type HealthStatus,
  type RiskStatus,
  type PortfolioStatus,
  type PositionSummary,
  type OrderSummary,
  type EventsSummary,
  type RuntimeStatus,
} from '../api/client';
import { riskDot, severityBadge, fmtNum, fmtPct, fmtTime, SafetyBanner, OfflineNotice, DegradedNotice, getReconciliationDotClass, getReconciliationLabel } from '../lib';

// ── Placeholder data ──────────────────────────────────────────────────────────

const PLACEHOLDER_RISK: RiskStatus = {
  day_start_equity: '500',
  current_equity: '500',
  risk_profile: { name: 'small_balanced' },
  risk_state: 'normal',
  daily_pnl_pct: '0',
  max_trade_risk_usdt: '7.5',
  reason: '占位数据 — 后端离线',
};

const PLACEHOLDER_PORTFOLIO: PortfolioStatus = {
  cash_balance_usdt: '500',
  total_equity_usdt: '500',
  unrealized_pnl_usdt: '0',
  positions: [] as PositionSummary[],
};

const PLACEHOLDER_EVENTS: EventsSummary[] = [
  {
    id: -1,
    event_type: 'backend_unavailable',
    severity: 'warning',
    component: 'dashboard',
    message: '后端离线，显示占位数据',
    created_at: new Date().toISOString(),
  },
];

const PLACEHOLDER_RUNTIME: RuntimeStatus = {
  last_cycle_status: null,
  last_cycle_time: null,
  last_error_message: '后端不可用',
  cycles_last_hour: 0,
  orders_last_hour: 0,
  supervisor_alive: null,
  ingestion_thread_alive: null,
  trading_thread_alive: null,
  uptime_seconds: null,
  last_heartbeat_time: null,
  last_component_error: null,
  heartbeat_stale_alerting: false,
  last_recovered_time: null,
  restart_attempts_ingestion_last_hour: 0,
  restart_attempts_trading_last_hour: 0,
  restart_exhausted_ingestion: false,
  restart_exhausted_trading: false,
  last_restart_time: null,
  trade_mode: 'paper_auto',
  live_trading_lock_enabled: false,
  execution_route_effective: 'paper',
  mode_transition_guard: null,
  shadow_executions_last_hour: 0,
  last_shadow_time: null,
  reconciliation: {
    status: 'ok',
    last_check_time: null,
    diff_summary: '占位数据 — 后端离线',
  },
};

// ── Sub-components ───────────────────────────────────────────────────────────

function LastUpdatedStamp({ date }: { date: Date | null }) {
  if (!date) return null;
  return (
      <span className="last-updated">
      更新时间 {date.toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })}
    </span>
  );
}

function StatusStrip({
  health,
  risk,
  healthFailed,
  riskFailed,
  runtime,
}: {
  health: HealthStatus | null;
  risk: RiskStatus | null;
  healthFailed: boolean;
  riskFailed: boolean;
  runtime: RuntimeStatus | null;
}) {
  const displayRisk = riskFailed ? PLACEHOLDER_RISK : risk;
  const reconciliation = runtime?.reconciliation;
  const reconStatus = reconciliation?.status ?? 'ok';
  const reconDotClass = getReconciliationDotClass(reconStatus);

  return (
    <div className="status-strip">
      <div className="status-pill">
        <span className="label">模式</span>
        <span className="value">
          {health?.trade_mode ?? (healthFailed ? 'paper_auto' : '—')}
        </span>
      </div>
      <div className="status-pill">
        <span className="label">真实交易</span>
        <span className="value">
          {health
            ? health.live_trading_enabled ? '已启用' : '未启用'
            : (healthFailed ? '未启用' : '—')}
        </span>
      </div>
      <div className="status-pill">
        <span className={`dot ${displayRisk ? riskDot(displayRisk.risk_state) : (riskFailed ? 'dot-placeholder' : 'dot-disabled')}`} />
        <span className="label">风险状态</span>
        <span className="value">{displayRisk?.risk_state ?? (riskFailed ? 'normal' : '—')}</span>
      </div>
      <div className="status-pill">
        <span className="label">档位</span>
        <span className="value">{displayRisk?.risk_profile.name ?? (riskFailed ? 'small_balanced' : '—')}</span>
      </div>
      <div className="status-pill">
        <span className={`dot ${reconDotClass}`} />
        <span className="label">对账</span>
        <span className="value">{reconStatus === 'ok' ? '正常' : reconStatus}</span>
      </div>
    </div>
  );
}

function MetricsGrid({
  portfolio,
  risk,
  riskFailed,
  portfolioFailed,
}: {
  portfolio: PortfolioStatus | null;
  risk: RiskStatus | null;
  riskFailed: boolean;
  portfolioFailed: boolean;
}) {
  const displayPortfolio = portfolioFailed ? PLACEHOLDER_PORTFOLIO : portfolio;
  const displayRisk      = riskFailed ? PLACEHOLDER_RISK : risk;

  const equity   = displayPortfolio?.total_equity_usdt ?? null;
  const cash     = displayPortfolio?.cash_balance_usdt ?? null;
  const pnlPct   = displayRisk?.daily_pnl_pct ?? null;
  const maxRisk  = displayRisk?.max_trade_risk_usdt ?? null;

  const pnlClass = pnlPct !== null
    ? (parseFloat(pnlPct) >= 0 ? 'positive' : 'negative')
    : (riskFailed ? 'placeholder' : '');

  return (
    <div className="metrics-grid">
      <div className="metric-card">
        <div className="metric-label">账户权益</div>
        <div className={`metric-value ${portfolioFailed && equity === null ? 'placeholder' : ''}`}>
          {equity !== null ? `$${fmtNum(equity)}` : (portfolioFailed ? '$500.00' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">现金余额</div>
        <div className={`metric-value ${portfolioFailed && cash === null ? 'placeholder' : ''}`}>
          {cash !== null ? `$${fmtNum(cash)}` : (portfolioFailed ? '$500.00' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">当日盈亏</div>
        <div className={`metric-value ${pnlClass}`}>
          {pnlPct !== null ? fmtPct(pnlPct) : (riskFailed ? '+0.00%' : '—')}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">单笔最大风险</div>
        <div className={`metric-value ${riskFailed && maxRisk === null ? 'placeholder' : ''}`}>
          {maxRisk !== null ? `$${fmtNum(maxRisk)}` : (riskFailed ? '$7.50' : '—')}
        </div>
      </div>
    </div>
  );
}

function PositionsSection({ positions }: { positions: PortfolioStatus['positions'] | null }) {
  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">持仓</span>
      </div>
      {positions === null || positions.length === 0 ? (
        <div className="empty-state">暂无持仓</div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>交易对</th>
                <th>数量</th>
                <th>平均开仓价</th>
                <th>市场价</th>
                <th>市值</th>
                <th>未实现盈亏</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.unrealized_pnl_usdt);
                const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
                return (
                  <tr key={i}>
                    <td>{p.symbol}</td>
                    <td>{fmtNum(p.qty, 4)}</td>
                    <td>${fmtNum(p.avg_entry_price)}</td>
                    <td>${fmtNum(p.market_price)}</td>
                    <td>${fmtNum(p.market_value_usdt)}</td>
                    <td className={pnlClass}>{fmtNum(p.unrealized_pnl_usdt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OrdersSection({ orders }: { orders: OrderSummary[] | null }) {
  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">最近订单</span>
      </div>
      {orders === null || orders.length === 0 ? (
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
                <tr key={o.id ?? `order-${o.symbol}-${o.created_at}`}>
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
  );
}

function EventsSection({
  events,
  isPlaceholder = false,
}: {
  events: EventsSummary[] | null;
  isPlaceholder?: boolean;
}) {
  const displayEvents = isPlaceholder ? PLACEHOLDER_EVENTS : (events ?? null);

  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">最近事件</span>
        {isPlaceholder && <span className="placeholder-tag">占位</span>}
      </div>
      {displayEvents === null || displayEvents.length === 0 ? (
        <div className="empty-state">暂无事件</div>
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
              {displayEvents.map((e) => (
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
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}小时 ${m}分` : `${h}小时`;
}

function ExecutionStatusBanner({ runtime }: { runtime: RuntimeStatus | null }) {
  if (!runtime) return null;

  const { trade_mode, live_trading_lock_enabled, execution_route_effective, mode_transition_guard } = runtime;

  let label: string;
  let labelClass: string;

  // Guard blocked — always show first, before any mode-specific text
  if (mode_transition_guard && mode_transition_guard.startsWith('blocked:')) {
    const reason = mode_transition_guard.replace('blocked: ', '');
    label = `模式切换被阻止，请查看 设置 > 执行控制`;
    labelClass = 'exec-banner-blocked';
    void reason; // stored in runtime.mode_transition_guard for Settings to surface
  } else if (live_trading_lock_enabled) {
    label = '真实执行被阻止，锁定已启用';
    labelClass = 'exec-banner-locked';
  } else if (trade_mode === 'paper_auto' || trade_mode === 'paper') {
    label = '纸面执行中';
    labelClass = 'exec-banner-paper';
  } else if (trade_mode === 'dry_run') {
    label = '演练模式，不会真实下单';
    labelClass = 'exec-banner-dryrun';
  } else if (trade_mode === 'live_shadow') {
    label = '影子模式，使用实时价格但不执行';
    labelClass = 'exec-banner-shadow';
  } else if (trade_mode === 'live_small_auto') {
    label = '真实执行中';
    labelClass = 'exec-banner-live';
  } else {
    label = `模式：${trade_mode}`;
    labelClass = 'exec-banner-default';
  }

  return (
    <div className={`exec-status-banner ${labelClass}`}>
      <span className="exec-status-dot" />
      <span className="exec-status-label">{label}</span>
      <span className="exec-status-route">路由&nbsp;{execution_route_effective}</span>
    </div>
  );
}

type BlockReason = { severity: 'danger' | 'warning'; label: string; reason: string };

function WhyBlockedPanel({
  runtime,
  risk,
  riskFailed,
}: {
  runtime: RuntimeStatus | null;
  risk: { risk_state: string; reason?: string } | null;
  riskFailed: boolean;
}) {
  if (!runtime) return null;

  const reasons: BlockReason[] = [];

  // Guard / transition blocked
  if (runtime.mode_transition_guard?.startsWith('blocked:')) {
    const reason = runtime.mode_transition_guard.replace('blocked: ', '');
    reasons.push({
      severity: 'danger',
      label: '模式切换阻断',
      reason,
    });
  }

  // Live lock active
  if (runtime.live_trading_lock_enabled) {
    reasons.push({
      severity: 'danger',
      label: '真实交易锁',
      reason: '真实下单被阻止，请前往 设置 > 执行控制 解除锁定',
    });
  }

  // Heartbeat stale
  if (runtime.heartbeat_stale_alerting) {
    const hint = runtime.last_heartbeat_time
      ? `最后心跳 ${fmtTime(runtime.last_heartbeat_time)}`
      : '心跳已丢失';
    reasons.push({
      severity: 'danger',
      label: '心跳异常',
      reason: `${hint}，交易进程可能已卡死，请重启`,
    });
  }

  // Restart exhausted
  if (runtime.restart_exhausted_ingestion) {
    reasons.push({
      severity: 'danger',
      label: '数据拉取耗尽',
      reason: '行情数据源连接失败，请检查网络或 API 限额',
    });
  }
  if (runtime.restart_exhausted_trading) {
    reasons.push({
      severity: 'danger',
      label: '交易线程耗尽',
      reason: '交易所 API 连接失败，请检查凭据或网络',
    });
  }

  // Risk breaker
  if (!riskFailed && risk) {
    if (risk.risk_state === 'global_pause') {
      reasons.push({
        severity: 'danger',
        label: '风险熔断',
        reason: '全局暂停交易（权益/风险触发），请查看风险面板',
      });
    } else if (risk.risk_state === 'no_new_positions') {
      reasons.push({
        severity: 'warning',
        label: '风险熔断',
        reason: risk.reason || '禁止开新仓位，请查看风险面板',
      });
    } else if (risk.risk_state === 'degraded') {
      reasons.push({
        severity: 'warning',
        label: '风险降级',
        reason: risk.reason || '风控降级中，请查看风险面板',
      });
    }
  } else if (riskFailed) {
    reasons.push({
      severity: 'warning',
      label: '风险状态不可用',
      reason: '无法获取风控状态，请检查后端连通性',
    });
  }

  // Reconciliation global pause
  if (runtime.reconciliation?.status === 'global_pause_recommended') {
    reasons.push({
      severity: 'danger',
      label: '对账建议暂停',
      reason: runtime.reconciliation.diff_summary || '对账发现严重差异，建议暂停所有交易',
    });
  }

  if (reasons.length === 0) return null;

  return (
    <div className="settings-section" style={{ marginBottom: '1rem' }}>
      <div className="settings-title">实盘阻断因素</div>
      {reasons.map((r, i) => (
        <div key={i} className={`reminder-row reminder-${r.severity}`}>
          <span className={`reminder-dot reminder-dot-${r.severity}`} />
          <span className="reminder-label">[{r.label}]</span>
          <span className="reminder-message">{r.reason}</span>
        </div>
      ))}
    </div>
  );
}

// ── Status helpers ────────────────────────────────────────────────────────────

/** Dot class for the heartbeat card — also reflects heartbeat_stale_alerting. */
function heartbeatDotClass(alerting: boolean, supervisorAlive: boolean | null): string {
  if (alerting) return 'dot-stale';
  if (supervisorAlive === false) return 'dot-degraded';
  if (supervisorAlive === true) return 'dot-normal';
  return 'dot-disabled';
}

/** Human-readable label for the heartbeat / heartbeat-alerting card. */
function heartbeatLabel(alerting: boolean, lastHeartbeat: string | null): { label: string; hint: string | null } {
  if (alerting) {
    return {
      label: '过期',
      hint: lastHeartbeat ? `最后心跳 ${fmtTime(lastHeartbeat)}，请重启交易进程` : '无心跳，请重启交易进程',
    };
  }
  return { label: '正常', hint: null };
}

/** Human-readable label for the restart-exhausted card. */
function restartExhaustedLabel(ingestion: boolean, trading: boolean): string {
  if (ingestion && trading) return '两侧均耗尽，请检查连接';
  if (ingestion) return '拉取线程耗尽，请检查数据源';
  if (trading) return '交易线程耗尽，请检查交易所 API';
  return '—';
}

function RuntimeSection({
  runtime,
  lastUpdated,
}: {
  runtime: RuntimeStatus | null;
  lastUpdated: Date | null;
}) {
  const display = runtime ?? PLACEHOLDER_RUNTIME;

  const hbDot = heartbeatDotClass(display.heartbeat_stale_alerting, display.supervisor_alive);
  const hbInfo = heartbeatLabel(display.heartbeat_stale_alerting, display.last_heartbeat_time);

  const reconStatus = display.reconciliation?.status ?? 'ok';
  const reconLabel = getReconciliationLabel(reconStatus);
  const reconIsNegative = reconStatus !== 'ok' && reconStatus !== 'unavailable';

  return (
    <div className="section">
      <div className="section-header">
        <span className="section-title">运行状态</span>
        <LastUpdatedStamp date={lastUpdated} />
      </div>
      <ExecutionStatusBanner runtime={runtime} />
      <div className="runtime-grid">
        <div className="metric-card">
          <div className="metric-label">心跳</div>
          <div className="metric-value">
            <span className={`dot ${hbDot}`} />
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">运行时长</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.uptime_seconds !== null ? formatUptime(display.uptime_seconds) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">最近心跳</div>
          <div className={`metric-value ${display.heartbeat_stale_alerting ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_heartbeat_time ? fmtTime(display.last_heartbeat_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">心跳告警</div>
          <div className={`metric-value ${display.heartbeat_stale_alerting ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.heartbeat_stale_alerting
              ? <span title={hbInfo.hint ?? undefined}>{hbInfo.label}</span>
              : (runtime ? hbInfo.label : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">心跳恢复时间</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_recovered_time ? fmtTime(display.last_recovered_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">最近周期</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_cycle_status ?? '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">每小时周期数</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.cycles_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">每小时订单数</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.orders_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">每小时影子执行数</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.shadow_executions_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">最近影子执行</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_shadow_time ? fmtTime(display.last_shadow_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">最近错误</div>
          <div className={`metric-value ${display.last_error_message ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_error_message ?? (runtime ? '无' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">组件错误</div>
          <div className={`metric-value ${display.last_component_error ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.last_component_error ?? (runtime ? '无' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">交易模式</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.trade_mode}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">真实交易锁</div>
          <div className={`metric-value ${display.live_trading_lock_enabled ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.live_trading_lock_enabled ? '开启' : '关闭'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">执行路由</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.execution_route_effective}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">模式守卫</div>
          <div className={`metric-value ${display.mode_transition_guard && display.mode_transition_guard.startsWith('blocked') ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {display.mode_transition_guard ?? (runtime ? '—' : '—')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">重启次数 I/T（1h）</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.restart_attempts_ingestion_last_hour}/{display.restart_attempts_trading_last_hour}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">重启耗尽</div>
          <div className={`metric-value ${(display.restart_exhausted_ingestion || display.restart_exhausted_trading) ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {restartExhaustedLabel(display.restart_exhausted_ingestion, display.restart_exhausted_trading)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">最近重启</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.last_restart_time ? fmtTime(display.last_restart_time) : '—'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">对账状态</div>
          <div className={`metric-value ${reconIsNegative && runtime ? 'negative' : (runtime ? '' : 'placeholder')}`}>
            {reconLabel}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">对账摘要</div>
          <div className={`metric-value ${runtime ? '' : 'placeholder'}`}>
            {display.reconciliation?.diff_summary ?? '—'}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Page component ─────────────────────────────────────────────────────────────

type ApiFailures = {
  health: boolean;
  risk: boolean;
  portfolio: boolean;
  orders: boolean;
  events: boolean;
  runtime: boolean;
};

export default function Overview() {
  const [health,    setHealth]    = useState<HealthStatus | null>(null);
  const [risk,      setRisk]      = useState<RiskStatus | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [orders,    setOrders]    = useState<OrderSummary[] | null>(null);
  const [events,    setEvents]    = useState<EventsSummary[] | null>(null);
  const [runtime,   setRuntime]   = useState<RuntimeStatus | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [failures,  setFailures]  = useState<ApiFailures>({
    health: false,
    risk: false,
    portfolio: false,
    orders: false,
    events: false,
    runtime: false,
  });

  const hasApiFailure = Object.values(failures).some(Boolean);

  const failedPanelLabels: string[] = [];
  if (failures.health)   failedPanelLabels.push('系统信息');
  if (failures.risk)     failedPanelLabels.push('风险');
  if (failures.portfolio) failedPanelLabels.push('账户');
  if (failures.orders)   failedPanelLabels.push('订单');
  if (failures.events)   failedPanelLabels.push('事件');
  if (failures.runtime)  failedPanelLabels.push('运行状态');

  const fetchAll = useCallback(() => {
    getHealth()
      .then((data) => { setHealth(data); setFailures((f) => ({ ...f, health: false })); })
      .catch(() => setFailures((f) => ({ ...f, health: true })));

    getRiskStatus(500, 500)
      .then((data) => { setRisk(data); setFailures((f) => ({ ...f, risk: false })); })
      .catch(() => setFailures((f) => ({ ...f, risk: true })));

    getPortfolioStatus(500)
      .then((data) => { setPortfolio(data); setFailures((f) => ({ ...f, portfolio: false })); })
      .catch(() => setFailures((f) => ({ ...f, portfolio: true })));

    getRecentOrders()
      .then((r) => { setOrders(r.orders); setFailures((f) => ({ ...f, orders: false })); })
      .catch(() => setFailures((f) => ({ ...f, orders: true })));

    getRecentEvents()
      .then((r) => { setEvents(r.events); setFailures((f) => ({ ...f, events: false })); })
      .catch(() => setFailures((f) => ({ ...f, events: true })));

    getRuntimeStatus()
      .then((data) => { setRuntime(data); setFailures((f) => ({ ...f, runtime: false })); })
      .catch(() => setFailures((f) => ({ ...f, runtime: true })));

    setLastUpdated(new Date());
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, [fetchAll]);

  return (
    <div className="page">
      <SafetyBanner />

      {hasApiFailure && (
        failedPanelLabels.length > 0
          ? <DegradedNotice failures={failedPanelLabels} />
          : <OfflineNotice />
      )}

      <WhyBlockedPanel
        runtime={failures.runtime ? null : runtime}
        risk={failures.risk ? null : risk}
        riskFailed={failures.risk}
      />

      <StatusStrip
        health={failures.health ? null : health}
        risk={failures.risk ? null : risk}
        healthFailed={failures.health}
        riskFailed={failures.risk}
        runtime={failures.runtime ? null : runtime}
      />

      <MetricsGrid
        portfolio={failures.portfolio ? null : portfolio}
        risk={failures.risk ? null : risk}
        riskFailed={failures.risk}
        portfolioFailed={failures.portfolio}
      />
      <PositionsSection positions={failures.portfolio ? null : (portfolio?.positions ?? null)} />
      <OrdersSection orders={failures.orders ? null : orders} />
      <EventsSection events={events} isPlaceholder={failures.events} />
      <RuntimeSection runtime={failures.runtime ? null : runtime} lastUpdated={lastUpdated} />
    </div>
  );
}
