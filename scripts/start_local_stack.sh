#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:5173}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
DASHBOARD_HOST="${DASHBOARD_HOST:-127.0.0.1}"
DASHBOARD_PORT="${DASHBOARD_PORT:-5173}"
WAIT_SECONDS="${WAIT_SECONDS:-45}"

RUN_DIR="${PROJECT_ROOT}/.run"
LOG_DIR="${PROJECT_ROOT}/logs"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
DASHBOARD_PID_FILE="${RUN_DIR}/dashboard.pid"
BACKEND_LOG="${LOG_DIR}/backend-dev.log"
DASHBOARD_LOG="${LOG_DIR}/dashboard-dev.log"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

info() { printf '[stack] %s\n' "$1"; }
ok() { printf '[ok] %s\n' "$1"; }
warn() { printf '[warn] %s\n' "$1"; }
fail() { printf '[fail] %s\n' "$1"; exit 1; }

is_pid_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

read_pid() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  tr -d ' \n' < "${file}"
}

wait_http() {
  local url="$1"
  local seconds="$2"
  local i
  for ((i = 1; i <= seconds; i++)); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_backend() {
  if curl -fsS --max-time 2 "${BACKEND_URL}/health" >/dev/null 2>&1; then
    ok "Backend already healthy at ${BACKEND_URL}"
    return 0
  fi

  local old_pid=""
  old_pid="$(read_pid "${BACKEND_PID_FILE}" || true)"
  if is_pid_running "${old_pid}"; then
    warn "Backend PID ${old_pid} exists but /health not ready yet; waiting"
  else
    info "Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
    nohup "${PROJECT_ROOT}/.venv/bin/python" -m uvicorn trading.main:app \
      --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" \
      >"${BACKEND_LOG}" 2>&1 &
    echo "$!" > "${BACKEND_PID_FILE}"
  fi

  wait_http "${BACKEND_URL}/health" "${WAIT_SECONDS}" \
    && ok "Backend is up" \
    || fail "Backend failed to start. See ${BACKEND_LOG}"
}

start_dashboard() {
  if curl -fsS --max-time 2 "${DASHBOARD_URL}" >/dev/null 2>&1; then
    ok "Dashboard already reachable at ${DASHBOARD_URL}"
    return 0
  fi

  local old_pid=""
  old_pid="$(read_pid "${DASHBOARD_PID_FILE}" || true)"
  if is_pid_running "${old_pid}"; then
    warn "Dashboard PID ${old_pid} exists but URL not ready yet; waiting"
  else
    info "Starting dashboard on ${DASHBOARD_HOST}:${DASHBOARD_PORT}"
    (
      cd "${PROJECT_ROOT}/dashboard"
      nohup npm run dev -- --host "${DASHBOARD_HOST}" --port "${DASHBOARD_PORT}" \
        >"${DASHBOARD_LOG}" 2>&1 &
      echo "$!" > "${DASHBOARD_PID_FILE}"
    )
  fi

  wait_http "${DASHBOARD_URL}" "${WAIT_SECONDS}" \
    && ok "Dashboard is up" \
    || fail "Dashboard failed to start. See ${DASHBOARD_LOG}"
}

print_json_field() {
  local json="$1"
  local expr="$2"
  DATA_JSON="${json}" python3 - "$expr" <<'PY'
import json
import os
import sys

expr = sys.argv[1]
data = json.loads(os.environ.get("DATA_JSON", "{}"))

def get_value(payload, path):
    cur = payload
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = None
    return cur

val = get_value(data, expr)
if isinstance(val, (dict, list)):
    print(json.dumps(val, ensure_ascii=False))
elif val is None:
    print("null")
else:
    print(val)
PY
}

run_healthcheck() {
  info "Running local health checks"

  local health runtime cp gate
  health="$(curl -fsS "${BACKEND_URL}/health")" || fail "GET /health failed"
  runtime="$(curl -fsS "${BACKEND_URL}/runtime/status")" || fail "GET /runtime/status failed"
  cp="$(curl -fsS "${BACKEND_URL}/runtime/control-plane")" || fail "GET /runtime/control-plane failed"
  gate="$(curl -fsS "${BACKEND_URL}/runtime/release-gate/live")" || fail "GET /runtime/release-gate/live failed"

  local status mode route lock gate_shadow gate_dry
  status="$(print_json_field "${health}" "status")"
  mode="$(print_json_field "${cp}" "trade_mode")"
  route="$(print_json_field "${cp}" "execution_route")"
  lock="$(print_json_field "${cp}" "lock_enabled")"
  gate_shadow="$(print_json_field "${gate}" "summary.allow_live_shadow")"
  gate_dry="$(print_json_field "${gate}" "summary.allow_live_small_auto_dry_run")"

  ok "/health status=${status}"
  ok "/runtime/control-plane mode=${mode} route=${route} lock_enabled=${lock}"
  ok "/runtime/release-gate/live allow_live_shadow=${gate_shadow} allow_live_small_auto_dry_run=${gate_dry}"

  if [[ "${gate_shadow}" != "True" && "${gate_shadow}" != "true" ]]; then
    warn "live_shadow gate is blocked:"
    print_json_field "${gate}" "summary.blocked_reasons"
  fi
  if [[ "${gate_dry}" != "True" && "${gate_dry}" != "true" ]]; then
    warn "live_small_auto dry-run gate is blocked (paper-safe expected initially):"
    print_json_field "${gate}" "summary.blocked_reasons"
  fi

  echo
  echo "Dashboard: ${DASHBOARD_URL}"
  echo "Backend:   ${BACKEND_URL}"
  echo "Logs:      ${BACKEND_LOG}, ${DASHBOARD_LOG}"
}

open_dashboard() {
  if command -v open >/dev/null 2>&1; then
    open "${DASHBOARD_URL}" >/dev/null 2>&1 || true
  fi
}

main() {
  info "Project root: ${PROJECT_ROOT}"
  start_backend
  start_dashboard
  run_healthcheck
  open_dashboard
}

main "$@"
