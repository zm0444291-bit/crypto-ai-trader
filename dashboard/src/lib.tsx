// ── Helpers ──────────────────────────────────────────────────────────────────

export function riskDot(state: string): string {
  switch (state) {
    case 'normal':            return 'dot-normal';
    case 'degraded':          return 'dot-degraded';
    case 'no_new_positions':  return 'dot-no-new';
    case 'global_pause':      return 'dot-global';
    case 'emergency_stop':    return 'dot-emergency';
    default:                  return 'dot-disabled';
  }
}

export function severityBadge(severity: string): string {
  switch (severity) {
    case 'info':    return 'badge badge-info';
    case 'warning': return 'badge badge-warning';
    case 'error':   return 'badge badge-danger';
    case 'success': return 'badge badge-success';
    default:        return 'badge badge-info';
  }
}

// Reconciliation status helpers — single source of truth for display labels and dot classes.
export type ReconciliationStatusValue =
  | 'ok'
  | 'balance_mismatch'
  | 'position_mismatch'
  | 'global_pause_recommended'
  | 'unavailable';

export function getReconciliationDotClass(status: ReconciliationStatusValue | string | null | undefined): string {
  switch (status) {
    case 'ok':               return 'dot-normal';
    case 'global_pause_recommended': return 'dot-stale';
    case 'balance_mismatch':
    case 'position_mismatch': return 'dot-degraded';
    default:                  return 'dot-disabled';
  }
}

export function getReconciliationLabel(status: ReconciliationStatusValue | string | null | undefined): string {
  switch (status) {
    case 'ok':               return '正常';
    case 'balance_mismatch':  return '余额差异';
    case 'position_mismatch': return '持仓差异';
    case 'global_pause_recommended': return '建议暂停';
    case 'unavailable':      return '不可用';
    default:                  return '—';
  }
}

export function fmtNum(v: string | number, decimals = 2): string {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(n)) return '—';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtPct(v: string | number): string {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

export function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch {
    return iso;
  }
}

// ── Shared components ─────────────────────────────────────────────────────────

export function SafetyBanner() {
  return (
    <div className="safety-banner">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <span>仅纸面盘只读看板：不会真实下单，也不提供真实交易控制</span>
    </div>
  );
}

export function OfflineNotice() {
  return (
    <div className="offline-notice">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>后端离线，当前显示占位数据</span>
    </div>
  );
}

export function DegradedNotice({ failures }: { failures: string[] }) {
  if (failures.length === 0) return null;
  // 6 = total number of monitored API panels (health, risk, portfolio, orders, events, runtime)
  const allFailed = failures.length >= 6;
  const msg = allFailed
    ? '后端离线，所有面板显示占位数据'
    : `以下面板数据暂不可用：${failures.join('、')}，` +
      (failures.includes('runtime') ? '运行状态不可用可能导致部分保护失效，' : '') +
      '其余面板数据为最新';
  return (
    <div className="offline-notice">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>{msg}</span>
    </div>
  );
}
