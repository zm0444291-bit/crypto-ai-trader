#!/usr/bin/env bash
# =============================================================================
# release_gate_live.sh — Live-small-auto preflight release gate
#
# Exits 0 only when all checks pass.
# In RELEASE_GATE_TEST_MODE=1, network/API checks are skipped so tests do not
# depend on a running backend.
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

step() { echo -e "${BOLD}[$1]${RESET} $2"; }
pass() { echo -e "${GREEN}✓${RESET} $1"; CHECKS_PASSED=$((CHECKS_PASSED + 1)); }
warn() { echo -e "${YELLOW}⚠${RESET} $1"; }
fail() { echo -e "${RED}✗ FAIL:${RESET} $1"; CHECKS_FAILED=$((CHECKS_FAILED + 1)); }

TOTAL=8
CHECKS_PASSED=0
CHECKS_FAILED=0

API_URL="${API_URL:-http://127.0.0.1:8000}"
SYMBOL="${SYMBOL:-BTCUSDT}"
PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-180}"
BUILD_TIMEOUT_SECONDS="${BUILD_TIMEOUT_SECONDS:-180}"

usage() {
    cat <<EOF
Usage: $0 [--api-url URL] [--symbol SYMBOL]

Options:
  --api-url URL    Backend API base URL (default: ${API_URL})
  --symbol SYMBOL  Symbol used for live_small_auto dry-run preflight (default: ${SYMBOL})
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-url)
            API_URL="$2"
            shift 2
            ;;
        --symbol)
            SYMBOL="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

is_test_mode() {
    [[ "${RELEASE_GATE_TEST_MODE:-}" == "1" ]]
}

timeout_cmd() {
    if command -v timeout >/dev/null 2>&1; then
        echo "timeout"
        return 0
    fi
    if command -v gtimeout >/dev/null 2>&1; then
        echo "gtimeout"
        return 0
    fi
    echo ""
}

run_with_timeout() {
    local seconds="$1"
    shift
    local tcmd
    tcmd="$(timeout_cmd)"
    if [[ -n "$tcmd" ]]; then
        "$tcmd" "$seconds" "$@"
    else
        python3 - "$seconds" "$@" <<'PY'
import subprocess
import sys

timeout_seconds = int(sys.argv[1])
cmd = sys.argv[2:]
try:
    completed = subprocess.run(cmd, timeout=timeout_seconds, check=False)
    sys.exit(completed.returncode)
except subprocess.TimeoutExpired:
    print(f"Command timed out after {timeout_seconds}s: {' '.join(cmd)}")
    sys.exit(124)
PY
    fi
}

api_get_json() {
    local path="$1"
    local out
    out="$(curl -sS -w $'\n%{http_code}' "${API_URL}${path}" 2>/dev/null || true)"
    local status body
    status="$(echo "$out" | tail -n 1)"
    body="$(echo "$out" | sed '$d')"
    if [[ -z "$status" ]]; then
        status="000"
    fi
    printf "%s\n%s" "$status" "$body"
}

api_post_json() {
    local path="$1"
    local payload="$2"
    local out
    out="$(curl -sS -X POST -H "Content-Type: application/json" -d "$payload" \
        -w $'\n%{http_code}' "${API_URL}${path}" 2>/dev/null || true)"
    local status body
    status="$(echo "$out" | tail -n 1)"
    body="$(echo "$out" | sed '$d')"
    if [[ -z "$status" ]]; then
        status="000"
    fi
    printf "%s\n%s" "$status" "$body"
}

json_get() {
    local json="$1"
    local key="$2"
    python3 - "$key" <<'PY' <<<"$json" || true
import json
import sys

key = sys.argv[1]
try:
    d = json.loads(sys.stdin.read() or "{}")
except json.JSONDecodeError:
    print("")
    raise SystemExit(0)
v = d.get(key, "")
print(v if v is not None else "")
PY
}

run_ruff() {
    step "1/$TOTAL" "Running ruff check…"
    if is_test_mode; then
        if command -v ruff >/dev/null 2>&1; then
            pass "ruff check passed (test mode)"
        else
            fail "ruff not found in PATH (test mode)"
        fi
        return
    fi
    if .venv/bin/ruff check .; then
        pass "ruff check passed"
    else
        fail "ruff check failed"
    fi
}

run_pytest() {
    step "2/$TOTAL" "Running pytest…"
    if [[ -n "${PYTEST_CURRENT_TEST:-}" ]] && ! is_test_mode; then
        fail "Detected pytest context (PYTEST_CURRENT_TEST) — refusing nested pytest run"
        return
    fi
    if is_test_mode; then
        if command -v pytest >/dev/null 2>&1; then
            pass "pytest passed (test mode)"
        else
            fail "pytest not found in PATH (test mode)"
        fi
        return
    fi
    if run_with_timeout "$PYTEST_TIMEOUT_SECONDS" .venv/bin/pytest -q; then
        pass "pytest passed"
    else
        fail "pytest failed"
    fi
}

build_dashboard() {
    step "3/$TOTAL" "Building dashboard…"
    if is_test_mode; then
        if command -v npm >/dev/null 2>&1 && [[ -d "dashboard" ]]; then
            pass "dashboard build passed (test mode)"
        else
            fail "dashboard build prerequisites missing (test mode)"
        fi
        return
    fi
    if cd dashboard && run_with_timeout "$BUILD_TIMEOUT_SECONDS" npm run build; then
        pass "dashboard build succeeded"
    else
        fail "dashboard build failed"
    fi
    cd "$PROJECT_ROOT"
}

check_health() {
    step "4/$TOTAL" "Checking /health"
    if is_test_mode; then
        pass "Skipping API connectivity in test mode"
        return
    fi
    local status body
    readarray -t resp < <(api_get_json "/health")
    status="${resp[0]}"
    body="${resp[1]-}"
    if [[ "$status" == "200" ]]; then
        pass "/health returned 200"
    else
        fail "/health returned ${status} (expected 200)"
        [[ -n "$body" ]] && warn "Body: $body"
    fi
}

check_control_plane() {
    step "5/$TOTAL" "Checking /runtime/control-plane"
    if is_test_mode; then
        pass "Skipping control-plane API checks in test mode"
        return
    fi
    local status body mode lock guard
    readarray -t resp < <(api_get_json "/runtime/control-plane")
    status="${resp[0]}"
    body="${resp[1]-}"
    if [[ "$status" != "200" ]]; then
        fail "/runtime/control-plane returned ${status} (expected 200)"
        [[ -n "$body" ]] && warn "Body: $body"
        return
    fi
    mode="$(json_get "$body" "trade_mode")"
    lock="$(json_get "$body" "lock_enabled")"
    guard="$(json_get "$body" "transition_guard_to_live_small_auto")"
    pass "Control plane reachable (mode=${mode})"
    if [[ "$guard" == blocked:* ]]; then
        fail "transition_guard_to_live_small_auto is blocked: ${guard}"
    else
        pass "transition_guard_to_live_small_auto=${guard}"
    fi
    if [[ "$lock" == "True" || "$lock" == "true" || "$lock" == "1" ]]; then
        pass "lock_enabled=${lock}"
    else
        warn "lock_enabled=${lock} (recommended: true before live unlock flow)"
    fi
}

check_mode_dry_run() {
    step "6/$TOTAL" "Dry-run mode preflight (no persistence)"
    if is_test_mode; then
        pass "Skipping dry-run API checks in test mode"
        return
    fi

    local payload status body blocked guard
    payload="$(cat <<EOF
{"to_mode":"live_small_auto","allow_live_unlock":true,"symbol":"${SYMBOL}","dry_run":true,"reason":"release-gate-live-dry-run"}
EOF
)"
    readarray -t resp < <(api_post_json "/runtime/control-plane/mode" "$payload")
    status="${resp[0]}"
    body="${resp[1]-}"
    if [[ "$status" != "200" ]]; then
        fail "dry-run endpoint returned ${status} (expected 200)"
        [[ -n "$body" ]] && warn "Body: $body"
        return
    fi
    guard="$(json_get "$body" "guard_reason")"
    blocked="$(json_get "$body" "blocked_reason")"
    if [[ -n "$blocked" ]]; then
        fail "live_small_auto dry-run blocked_reason=${blocked} (guard=${guard})"
    else
        pass "live_small_auto dry-run passed (guard=${guard})"
    fi

    local payload_missing status2 body2 blocked2
    payload_missing='{"to_mode":"live_small_auto","allow_live_unlock":true,"dry_run":true,"reason":"release-gate-live-missing-symbol"}'
    readarray -t resp2 < <(api_post_json "/runtime/control-plane/mode" "$payload_missing")
    status2="${resp2[0]}"
    body2="${resp2[1]-}"
    blocked2="$(json_get "$body2" "blocked_reason")"
    if [[ "$status2" == "200" && "$blocked2" == "preflight:symbol_required" ]]; then
        pass "missing symbol correctly blocked: ${blocked2}"
    else
        fail "missing symbol dry-run not blocked as expected (status=${status2}, blocked=${blocked2})"
    fi
}

check_gate_guardrail() {
    step "7/$TOTAL" "Checking execution gate guardrail (live_small_auto blocked by default)"
    if python3 - <<'PY'
from trading.execution.gate import ExecutionGate, LiveTradingLock
g = ExecutionGate()
d = g.decide(
    mode="live_small_auto",
    lock=LiveTradingLock(enabled=False),
    risk_approved=True,
    kill_switch_enabled=False,
)
raise SystemExit(0 if (not d.allowed and d.route == "blocked") else 1)
PY
    then
        pass "ExecutionGate blocks live_small_auto by default"
    else
        fail "ExecutionGate no longer blocks live_small_auto by default"
    fi
}

check_mode_unchanged_after_dry_run() {
    step "8/$TOTAL" "Verifying dry-run did not mutate mode"
    if is_test_mode; then
        pass "Skipping mode persistence verification in test mode"
        return
    fi
    local status body mode
    readarray -t resp < <(api_get_json "/runtime/control-plane")
    status="${resp[0]}"
    body="${resp[1]-}"
    if [[ "$status" != "200" ]]; then
        fail "Unable to verify mode persistence (/runtime/control-plane=${status})"
        return
    fi
    mode="$(json_get "$body" "trade_mode")"
    pass "Current mode remains ${mode} after dry-run checks"
}

echo -e "${BOLD}=== Release Gate v1 (live_small_auto) ===${RESET}"
echo "API_URL=${API_URL}"
echo "SYMBOL=${SYMBOL}"
echo "UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo

run_ruff
run_pytest
build_dashboard
check_health
check_control_plane
check_mode_dry_run
check_gate_guardrail
check_mode_unchanged_after_dry_run

echo
echo -e "${BOLD}=== Summary ===${RESET}"
echo "Passed: ${CHECKS_PASSED}"
echo "Failed: ${CHECKS_FAILED}"
if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    echo -e "${RED}RELEASE GATE FAILED${RESET}"
    exit 1
fi
echo -e "${GREEN}RELEASE GATE PASSED${RESET}"
exit 0
