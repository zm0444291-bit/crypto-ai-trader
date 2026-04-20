import { useCallback, useEffect, useState } from 'react';
import { fmtTime } from '../lib';
import {
  getHealth,
  getRuntimeStatus,
  getMarketDataStatus,
  getControlPlane,
  setControlPlaneMode,
  setLiveLock,
  exitLocalSystem,
  type HealthStatus,
  type RuntimeStatus,
  type MarketDataStatus,
  type ControlPlaneResponse,
  type TradeMode,
  type ModeChangeResponse,
  type LiveLockChangeResponse,
} from '../api/client';

const PLACEHOLDER_CONTROL: ControlPlaneResponse = {
  trade_mode: 'paper_auto',
  lock_enabled: false,
  lock_reason: null,
  execution_route: 'paper',
  transition_guard_to_live_small_auto: '—',
};

const TRADE_MODES: TradeMode[] = ['paused', 'paper_auto', 'live_shadow', 'live_small_auto'];

function FeedbackBanner({
  success,
  message,
}: {
  success: boolean;
  message: string;
}) {
  return (
    <div className={`feedback-banner ${success ? 'feedback-success' : 'feedback-error'}`}>
      <span>{success ? '✓' : '✗'}</span>
      <span>{message}</span>
    </div>
  );
}

export default function Settings() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [marketData, setMarketData] = useState<MarketDataStatus | null>(null);
  const [controlPlane, setControlPlane] = useState<ControlPlaneResponse | null>(null);
  const [controlPlaneFailed, setControlPlaneFailed] = useState(false);
  const [runtimeFailed, setRuntimeFailed] = useState(false);

  const [modeValue, setModeValue] = useState<string>('paper_auto');
  const [allowLiveUnlock, setAllowLiveUnlock] = useState(false);
  const [modeReason, setModeReason] = useState('');
  const [modeLoading, setModeLoading] = useState(false);
  const [modeFeedback, setModeFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [modeDirty, setModeDirty] = useState(false);
  const [modeApplying, setModeApplying] = useState(false);

  const [lockEnabled, setLockEnabled] = useState(false);
  const [lockReason, setLockReason] = useState('');
  const [lockLoading, setLockLoading] = useState(false);
  const [lockFeedback, setLockFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [lockDirty, setLockDirty] = useState(false);
  const [lockApplying, setLockApplying] = useState(false);
  const [exitLoading, setExitLoading] = useState(false);
  const [exitFeedback, setExitFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const refreshControlPlane = useCallback(() => {
    getControlPlane()
      .then((data) => { setControlPlane(data); setControlPlaneFailed(false); })
      .catch(() => setControlPlaneFailed(true));
    getRuntimeStatus()
      .then((data) => { setRuntime(data); setRuntimeFailed(false); })
      .catch(() => setRuntimeFailed(true));
  }, []);

  // Sync form defaults from controlPlane — only when not dirty and not applying
  useEffect(() => {
    if (!controlPlane) return;
    if (!modeDirty && !modeApplying) {
      setModeValue(controlPlane.trade_mode);
    }
    if (!lockDirty && !lockApplying) {
      setLockEnabled(controlPlane.lock_enabled);
      setLockReason(controlPlane.lock_reason ?? '');
    }
  }, [controlPlane, modeDirty, modeApplying, lockDirty, lockApplying]);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => {});
    getRuntimeStatus()
      .then((data) => { setRuntime(data); setRuntimeFailed(false); })
      .catch(() => setRuntimeFailed(true));
    getMarketDataStatus()
      .then(setMarketData)
      .catch(() => {});
    getControlPlane()
      .then((data) => { setControlPlane(data); setControlPlaneFailed(false); })
      .catch(() => setControlPlaneFailed(true));
  }, []);

  const handleApplyMode = async () => {
    setModeApplying(true);
    setModeLoading(true);
    setModeFeedback(null);
    try {
      const res: ModeChangeResponse = await setControlPlaneMode(
        modeValue as TradeMode,
        allowLiveUnlock,
        modeReason || undefined,
      );
      setModeFeedback({ success: res.success, message: res.guard_reason });
      if (res.success) {
        setModeReason('');
        setAllowLiveUnlock(false);
        setModeDirty(false);
        await refreshControlPlane();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      setModeFeedback({ success: false, message: msg });
    } finally {
      setModeLoading(false);
      setModeApplying(false);
    }
  };

  const handleApplyLock = async () => {
    setLockApplying(true);
    setLockLoading(true);
    setLockFeedback(null);
    try {
      const res: LiveLockChangeResponse = await setLiveLock(
        lockEnabled,
        lockReason || undefined,
      );
      setLockFeedback({ success: res.success, message: res.reason });
      if (res.success) {
        setLockReason('');
        setLockDirty(false);
        await refreshControlPlane();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      setLockFeedback({ success: false, message: msg });
    } finally {
      setLockLoading(false);
      setLockApplying(false);
    }
  };

  const handleExitSystem = async () => {
    const ok = window.confirm('确认一键退出系统？这将停止后端、运行时和前端开发服务。');
    if (!ok) return;

    setExitLoading(true);
    setExitFeedback(null);
    try {
      const res = await exitLocalSystem(true);
      setExitFeedback({
        success: true,
        message: `已执行：${res.message}。服务将在约 1-2 秒内停止。`,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : '未知错误';
      setExitFeedback({ success: false, message: msg });
    } finally {
      setExitLoading(false);
    }
  };

  const isBlocked = (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto.startsWith('blocked:');
  const guardReason = (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto;

  return (
    <div className="page">
      <div className="safety-notice">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0, marginTop: 1 }} aria-hidden="true">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <span>
          当前看板仅运行纸面盘模式，不使用真实资金。真实交易需在后续里程碑中显式解锁。
        </span>
      </div>

      {isBlocked && (
        <div className="guard-warning-banner">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <span>切换守卫已生效 — {guardReason}</span>
        </div>
      )}

      {/* ── Current Risk Reminders (read-only, derived from runtime/control-plane) ── */}
      {!runtimeFailed && runtime && (
        (() => {
          const reminders: { severity: 'danger' | 'warning'; message: string }[] = [];
          if (runtime.heartbeat_stale_alerting) {
            reminders.push({
              severity: 'danger',
              message: '心跳已过期，请重启交易进程',
            });
          }
          if (runtime.restart_exhausted_ingestion) {
            reminders.push({
              severity: 'danger',
              message: '行情拉取重启次数耗尽，请检查数据源连通性',
            });
          }
          if (runtime.restart_exhausted_trading) {
            reminders.push({
              severity: 'danger',
              message: '交易线程重启次数耗尽，请检查交易所 API 凭据',
            });
          }
          if (runtime.live_trading_lock_enabled) {
            reminders.push({
              severity: 'warning',
              message: '真实交易锁已启用，真实下单被阻止',
            });
          }
          if (reminders.length === 0) return null;
          return (
            <div className="settings-section">
              <div className="settings-title">当前风险提醒</div>
              {reminders.map((r, i) => (
                <div key={i} className={`reminder-row reminder-${r.severity}`}>
                  <span className={`reminder-dot reminder-dot-${r.severity}`} />
                  <span className="reminder-message">{r.message}</span>
                </div>
              ))}
            </div>
          );
        })()
      )}

      <div className="settings-section">
        <div className="settings-title">系统信息</div>
        <div className="settings-row">
          <span className="row-label">模式</span>
          <span className="row-value">
            {controlPlaneFailed
              ? (runtime?.trade_mode ?? health?.trade_mode ?? '—')
              : (controlPlane?.trade_mode ?? runtime?.trade_mode ?? health?.trade_mode ?? '—')}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">已启用真实交易</span>
          <span className="row-value">{health?.live_trading_enabled ? '是' : '否'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">最近周期</span>
          <span className="row-value">{runtimeFailed ? '—' : (runtime?.last_cycle_status ?? '—')}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">每小时周期数</span>
          <span className="row-value">{runtimeFailed ? '—' : (runtime?.cycles_last_hour ?? '—')}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">每小时订单数</span>
          <span className="row-value">{runtimeFailed ? '—' : (runtime?.orders_last_hour ?? '—')}</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">市场数据</div>
        <div className="settings-row">
          <span className="row-label">连接状态</span>
          <span className="row-value">{marketData?.connected ? '已连接' : '未连接'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">交易对</span>
          <span className="row-value">{(marketData?.symbols ?? []).join(', ') || '—'}</span>
        </div>
        <div className="settings-row">
          <span className="row-label">周期</span>
          <span className="row-value">{(marketData?.timeframes ?? []).join(', ') || '—'}</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">数据库</div>
        <div className="settings-row">
          <span className="row-label">位置</span>
          <span className="row-value">data/crypto_ai_trader.sqlite3</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">对账（纸面安全）</div>
        <div className="settings-row">
          <span className="row-label">对账状态</span>
          <span className={`row-value ${
            runtimeFailed || !runtime?.reconciliation
              ? ''
              : runtime.reconciliation.status === 'ok'
              ? ''
              : runtime.reconciliation.status === 'global_pause_recommended'
              ? 'negative'
              : runtime.reconciliation.status === 'balance_mismatch' || runtime.reconciliation.status === 'position_mismatch'
              ? 'negative'
              : ''
          }`}>
            {runtimeFailed || !runtime?.reconciliation
              ? '—'
              : runtime.reconciliation.status === 'ok'
              ? '正常'
              : runtime.reconciliation.status === 'balance_mismatch'
              ? '余额差异'
              : runtime.reconciliation.status === 'position_mismatch'
              ? '持仓差异'
              : runtime.reconciliation.status === 'global_pause_recommended'
              ? '建议全局暂停'
              : runtime.reconciliation.status === 'unavailable'
              ? '不可用'
              : runtime.reconciliation.status ?? '—'}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">最后检查时间</span>
          <span className="row-value">
            {runtimeFailed || !runtime?.reconciliation
              ? '—'
              : runtime.reconciliation.last_check_time
              ? fmtTime(runtime.reconciliation.last_check_time)
              : '—'}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">差异摘要</span>
          <span className="row-value">
            {runtimeFailed || !runtime?.reconciliation ? '—' : (runtime.reconciliation.diff_summary ?? '—')}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">阈值：余额容差</span>
          <span className="row-value">1.0 USDT</span>
        </div>
        <div className="settings-row">
          <span className="row-label">阈值：余额临界值</span>
          <span className="row-value">10.0 USDT</span>
        </div>
        <div className="settings-row">
          <span className="row-label">阈值：持仓数量容差</span>
          <span className="row-value">0.0001（绝对值）</span>
        </div>
        <div className="settings-row">
          <span className="row-label">阈值：持仓临界数量</span>
          <span className="row-value">3（触发全局暂停建议）</span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">执行控制平面</div>
        <div className="settings-row">
          <span className="row-label">锁定状态</span>
          <span className="row-value">
            {controlPlaneFailed
                ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).lock_enabled
                ? '是'
                : '否'}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">锁定原因</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : ((controlPlane ?? PLACEHOLDER_CONTROL).lock_reason ?? '—')}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">执行路由</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).execution_route}
          </span>
        </div>
        <div className="settings-row">
          <span className="row-label">切换守卫</span>
          <span className="row-value">
            {controlPlaneFailed
              ? '—'
              : (controlPlane ?? PLACEHOLDER_CONTROL).transition_guard_to_live_small_auto}
          </span>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">执行控制操作</div>

        <div className="control-action-group">
          <div className="control-action-label">模式</div>
          <div className="control-action-row">
            <select
              className="filter-select"
              value={modeValue}
              onChange={(e) => {
                setModeValue(e.target.value);
                setModeDirty(true);
              }}
            >
              {TRADE_MODES.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={allowLiveUnlock}
                onChange={(e) => {
                  setAllowLiveUnlock(e.target.checked);
                  setModeDirty(true);
                }}
              />
              <span>允许解锁真实交易</span>
            </label>
          </div>
          <input
            className="control-input"
            type="text"
            placeholder="原因（可选）"
            value={modeReason}
            onChange={(e) => {
              setModeReason(e.target.value);
              setModeDirty(true);
            }}
          />
          {modeFeedback && (
            <FeedbackBanner success={modeFeedback.success} message={modeFeedback.message} />
          )}
          <button
            className="control-btn"
            onClick={handleApplyMode}
            disabled={modeLoading}
          >
            {modeLoading ? '应用中…' : '应用模式'}
          </button>
        </div>

        <div className="control-action-group">
          <div className="control-action-label">真实交易锁</div>
          <div className="control-action-row">
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={lockEnabled}
                onChange={(e) => {
                  setLockEnabled(e.target.checked);
                  setLockDirty(true);
                }}
              />
              <span>启用</span>
            </label>
          </div>
          <input
            className="control-input"
            type="text"
            placeholder="原因（可选）"
            value={lockReason}
            onChange={(e) => {
              setLockReason(e.target.value);
              setLockDirty(true);
            }}
          />
          {lockFeedback && (
            <FeedbackBanner success={lockFeedback.success} message={lockFeedback.message} />
          )}
          <button
            className="control-btn"
            onClick={handleApplyLock}
            disabled={lockLoading}
          >
            {lockLoading ? '应用中…' : '应用锁设置'}
          </button>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-title">系统退出</div>
        <div className="control-action-group">
          <div className="control-action-label">一键关闭本地服务</div>
          {exitFeedback && (
            <FeedbackBanner success={exitFeedback.success} message={exitFeedback.message} />
          )}
          <button
            className="control-btn"
            onClick={handleExitSystem}
            disabled={exitLoading}
          >
            {exitLoading ? '执行中…' : '一键退出系统'}
          </button>
        </div>
      </div>
    </div>
  );
}
