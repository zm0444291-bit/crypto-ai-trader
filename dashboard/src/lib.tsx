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
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric',
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
      <span>Read-only paper-mode dashboard — no trade execution, no live trading controls</span>
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
      <span>Backend offline — showing placeholder data</span>
    </div>
  );
}
