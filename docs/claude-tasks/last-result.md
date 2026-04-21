# Task Result: release_gate_live Dashboard 可视化联动

**Date:** 2026-04-21
**Task:** 实盘前最后一道护栏：release_gate_live 与 Dashboard 联动可视化

---

## 1. 变更摘要 (≤10条)

1. **`GET /runtime/release-gate/live`** (后端) — 新增只读 API 端点，返回 environment/control_plane/risk/health/checks/summary 六层结构；返回 `allow_live_shadow`、`allow_live_small_auto_dry_run` 两个布尔值及 `blocked_reasons[]`；完全不写事件，保证幂等。

2. **Pydantic 响应模型** (后端) — 新增 `ReleaseGateCheck`、`ReleaseGateEnvironment`、`ReleaseGateControlPlane`、`ReleaseGateRisk`、`ReleaseGateHealth`、`ReleaseGateSummary`、`ReleaseGateResponse` 七个模型，置于 `routes_runtime.py` 独立区块。

3. **`_resolve_risk_info()`** (后端) — 复用既有 risk 解析逻辑（day_baseline_set + fills + classify_daily_loss），扩展为返回完整 equity 信息（day_start_equity/current_equity/daily_pnl_pct）供 release gate 使用。

4. **`getReleaseGateStatus()`** (前端 client.ts) — 新增 API 函数和 TypeScript 类型定义，调用 `GET /runtime/release-gate/live` 并返回强类型 `ReleaseGateResponse`。

5. **"实盘前置检查（只读）"区块** (Settings.tsx) — 新增 UI 区块：显示 allow_live_shadow/allow_live_small_auto_dry_run 两个状态徽章；列出所有 check 项（✓/✗/⚠）；展示 blocked_reasons；底部安全免责文案"dry-run 通过 ≠ 允许真实下单"。

6. **Fail-closed 保证** — DB 初始化失败、API 处理异常、心跳丢失均返回 `allow=false` + blocked_reasons，从不抛出 500；风险状态 unavailable 时 warn 而非 fail。

7. **`tests/integration/test_release_gate_live_api.py`** — 新增 10 个测试覆盖：happy path 结构完整性、key/secret 绝不回显（仅 presence 布尔值）、预期 check codes、live_shadow 允许条件、dry-run 阻断条件（无 key/secret）、fail-closed 场景（无 baseline/heartbeat stale/lock enabled）、只读保证（调用前后事件数不变、3 次重复调用不累积）。

8. **BINANCE_API_KEY/SECRET 安全处理** — 仅检查环境变量是否存在（`bool(os.environ.get(...).strip())`），返回值只有布尔 flag，真实 key 绝不出现在 API 响应或日志中。

9. **Ruff E501 全面修复** — routes_runtime.py 新增代码大量超过 100 字符限制，通过提取局部字符串变量（`_msg_ok`/`_msg_fail` 等）重构，修复 29 处 E501 行长度违规。

10. **paper-safe 默认门控未变** — 所有判定逻辑依赖既有 `ExecutionGate`/`LiveTradingLock`/`validate_mode_transition`，不引入新的门控旁路；live_small_auto 仍需双重解锁（transition_guard + allow_live_unlock）。

---

## 2. 修改文件清单

| 文件 | 操作 |
|------|------|
| `trading/dashboard_api/routes_runtime.py` | 新增 ReleaseGateResponse Pydantic 模型、`read_release_gate_live()` 端点、`_fail_closed_release_gate()`、`_resolve_risk_info()`；移除未使用变量 `last_heartbeat_time` |
| `dashboard/src/api/client.ts` | 新增 `ReleaseGateResponse` 等 TypeScript 类型 + `getReleaseGateStatus()` 函数 |
| `dashboard/src/pages/Settings.tsx` | 新增"实盘前置检查（只读）"区块 + `releaseGate`/`releaseGateFailed` state + 加载逻辑 |
| `tests/integration/test_release_gate_live_api.py` | 新增 10 个测试（happy path / fail-closed / read-only） |

---

## 3. 验收命令与结果

```bash
# ① ruff check
$ .venv/bin/ruff check trading/dashboard_api tests/integration
All checks passed!                                          ✓

# ② pytest release_gate_live_api
$ .venv/bin/pytest -q tests/integration/test_release_gate_live_api.py
..........                                                    [100%]
10 passed in 0.54s                                          ✓

# ③ pytest runtime_status_api + control_plane_mode_p1 (回归)
$ .venv/bin/pytest -q tests/integration/test_runtime_status_api.py \
                     tests/integration/test_control_plane_mode_p1.py
........................................................       [100%]
46 passed in 0.97s                                           ✓

# ④ pytest integration -k "release or runtime or dashboard"
$ .venv/bin/pytest -q tests/integration -k "release or runtime or dashboard"
.............................................................. [100%]
62 passed, 21 deselected in 1.37s                            ✓

# ⑤ dashboard build
$ cd dashboard && npm run build
vite v5.4.21 building for production...
✓ 50 modules transformed.
dist/assets/index-DzbXl4ED.css   13.05 kB │ gzip:  2.83 kB
dist/assets/index-DHI5MMt-.js   234.21 kB │ gzip: 71.93 kB
✓ built in 360ms                                           ✓
```

---

## 4. 风险与后续建议 (≤3条)

1. **前端 UI 尚未在真实运行时环境验证** — Settings.tsx 的新 UI 依赖 `getReleaseGateStatus()` 在 `useEffect` 初始化时的网络调用；真实环境若 API 未启动或响应慢，页面降级行为（"检查结果不可用"）已实现但未做浏览器端模拟测试。建议在真实 backend 运行状态下手动验证。

2. **exchanges.yaml 解析失败时 dry-run 仍可尝试** — 当 `exchanges_yaml_ok=False` 时，`allow_live_small_auto_dry_run=false`；但这只阻止 dry-run 评估通过，ExecutionGate 的静态阻断依然有效。整体安全，但 UI 应明确告知用户配置问题需先修复。

3. **长期无维护风险** — risk_state unavailable 时 warn 不 fail，但如果系统长期处于无 baseline 状态（比如重启后 24 小时未跑交易），用户可能误以为一切正常。建议在 runbook 中补充"每日起始基线缺失"的告警处理流程。