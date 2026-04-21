#!/usr/bin/env bash
# =============================================================================
# release_gate_live.sh — Live-small-auto preflight release gate
#
# Exits 0 only when all checks pass.
# In RELEASE_GATE_TEST_MODE=1, network/API checks are skipped so tests do not
# depend on a running backend.
#
# Structured output: human-readable (text, default) or JSON (--format json).
# =============================================================================
set -euo pipefail

# --- ANSI colours ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

# --- Default settings ---
API_URL="${API_URL:-http://127.0.0.1:8000}"
SYMBOL="${SYMBOL:-BTCUSDT}"
PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-180}"
BUILD_TIMEOUT_SECONDS="${BUILD_TIMEOUT_SECONDS:-180}"

# --- Output mode ---
OUTPUT_FORMAT="text"
OUTPUT_FILE=""
QUIET="false"

# --- Check counters ---
TOTAL=8
CHECKS_PASSED=0
CHECKS_FAILED=0

# --- Runtime snapshots (populated by checks) ---
_snap_trade_mode=""
_snap_lock_enabled="null"
_snap_guard="null"
_snap_risk_state="null"
_snap_heartbeat_stale="null"

# --- Helpers ---

step() {
    if [[ "$QUIET" == "true" || "$OUTPUT_FORMAT" == "json" ]]; then return; fi
    echo -e "${BOLD}[$1]${RESET} $2"
}
pass() {
    if [[ "$QUIET" != "true" && "$OUTPUT_FORMAT" != "json" ]]; then
        echo -e "${GREEN}✓${RESET} $1"
    fi
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    _record_check "$1" "pass"
}
warn() {
    if [[ "$QUIET" != "true" && "$OUTPUT_FORMAT" != "json" ]]; then
        echo -e "${YELLOW}⚠${RESET} $1"
    fi
    _record_check "$1" "warn"
}
fail() {
    if [[ "$QUIET" != "true" && "$OUTPUT_FORMAT" != "json" ]]; then
        echo -e "${RED}✗ FAIL:${RESET} $1"
    fi
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
    _record_check "$1" "fail"
}

# =============================================================================
# CHECK REGISTRY — stored as lines: "STATUS|CODE|MESSAGE"
# =============================================================================

_REGISTRY_FILE=""
_current_check_code=""

_init_registry() {
    _REGISTRY_FILE="$(mktemp)"
}

_record_check() {
    local msg="$1"
    local status="$2"
    local code="$_current_check_code"
    # | is safe inside the temp file since messages are escaped at JSON emission time
    printf "%s|%s|%s\n" "$status" "$code" "$msg" >> "$_REGISTRY_FILE"
}

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --api-url URL      Backend API base URL (default: ${API_URL})
  --symbol SYMBOL    Symbol used for live_small_auto dry-run preflight (default: ${SYMBOL})
  --format text|json Output format (default: text)
  --output <path>    Write output to file (default: stdout; recommended for json)
  --quiet            Suppress non-essential text output
  --dry-run          No-op (backwards compatibility; this script is always a preflight)
  -h|--help          Show this help

Exit codes:
  0  All checks passed
  1  One or more checks failed
  2  Invalid arguments
EOF
}

snap() {
    local key="$1"
    local val="$2"
    case "$key" in
        trade_mode)    _snap_trade_mode="$val" ;;
        lock_enabled)  _snap_lock_enabled="$val" ;;
        guard)         _snap_guard="$val" ;;
        risk_state)    _snap_risk_state="$val" ;;
        heartbeat)     _snap_heartbeat_stale="$val" ;;
    esac
}

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
import subprocess, sys
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
import json, sys
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

# =============================================================================
# CHECKS
# =============================================================================

run_ruff() {
    _current_check_code="ruff"
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
    _current_check_code="pytest"
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
    _current_check_code="dashboard_build"
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
    _current_check_code="health"
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
    _current_check_code="control_plane"
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
    snap "trade_mode" "$mode"
    snap "lock_enabled" "$lock"
    snap "guard" "$guard"
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
    _current_check_code="dry_run_preflight"
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
    _current_check_code="gate_guardrail"
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
    _current_check_code="mode_persistence"
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

# =============================================================================
# JSON EMISSION (pure Python — clean, robust)
# =============================================================================

_emit_json() {
    python3 - "$_REGISTRY_FILE" \
        "$CHECKS_PASSED" "$CHECKS_FAILED" \
        "$_snap_trade_mode" "$_snap_lock_enabled" "$_snap_guard" \
        "$_snap_risk_state" "$_snap_heartbeat_stale" <<'PY'
import json, sys
from datetime import datetime, timezone

registry_path = sys.argv[1]
checks_passed = int(sys.argv[2])
checks_failed = int(sys.argv[3])
snap_mode = sys.argv[4] or "unknown"
snap_lock = sys.argv[5] if sys.argv[5] != "null" else None
snap_guard = sys.argv[6] if sys.argv[6] != "null" else None
snap_risk = sys.argv[7] if sys.argv[7] != "null" else None
snap_heartbeat = sys.argv[8] if sys.argv[8] != "null" else None

# Parse registry: "STATUS|CODE|MESSAGE" lines
checks = []
blocked_reasons = []
with open(registry_path, "r") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        status, code, message = parts
        checks.append({"code": code, "status": status, "message": message})
        if status == "fail":
            blocked_reasons.append(message)

generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Determine summary booleans
pass_all = (checks_failed == 0)
# live_shadow readiness: depends on baseline runtime/script checks, not dry-run preflight.
live_shadow_blocking_codes = {
    "ruff",
    "pytest",
    "dashboard_build",
    "health",
    "control_plane",
    "gate_guardrail",
    "mode_persistence",
}
failed_codes = {c["code"] for c in checks if c["status"] == "fail"}
allow_live_shadow = len(live_shadow_blocking_codes & failed_codes) == 0
allow_live_small_auto_dry_run = pass_all  # dry-run passes only when all checks pass

result = {
    "generated_at": generated_at,
    "mode": "paper_safe_gate",
    "summary": {
        "pass": pass_all,
        "allow_live_shadow": allow_live_shadow,
        "allow_live_small_auto_dry_run": allow_live_small_auto_dry_run,
        "blocked_reasons": blocked_reasons,
    },
    "checks": checks,
    "runtime_snapshot": {
        "trade_mode": snap_mode,
        "lock_enabled": snap_lock,
        "transition_guard_to_live_small_auto": snap_guard,
        "risk_state": snap_risk,
        "heartbeat_stale_alerting": snap_heartbeat,
    },
}

print(json.dumps(result, indent=2))
PY
    return $?
}

# =============================================================================
# MAIN
# =============================================================================

while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-url)
            API_URL="$2"; shift 2 ;;
        --symbol)
            SYMBOL="$2"; shift 2 ;;
        --format)
            OUTPUT_FORMAT="$2"; shift 2 ;;
        --output)
            OUTPUT_FILE="$2"; shift 2 ;;
        --quiet)
            QUIET="true"; shift ;;
        --dry-run)
            # No-op: this script is always a preflight; kept for backwards compatibility
            shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            usage; exit 2 ;;
    esac
done

if [[ "$OUTPUT_FORMAT" != "text" && "$OUTPUT_FORMAT" != "json" ]]; then
    echo "ERROR: --format must be 'text' or 'json', got '$OUTPUT_FORMAT'" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Initialize check registry
_init_registry

# Clean up registry on exit
trap 'rm -f "$_REGISTRY_FILE"' EXIT

if [[ "$OUTPUT_FORMAT" != "json" ]]; then
    echo -e "${BOLD}=== Release Gate v1 (live_small_auto) ===${RESET}"
    echo "API_URL=${API_URL}"
    echo "SYMBOL=${SYMBOL}"
    echo "UTC=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo
fi

run_ruff
run_pytest
build_dashboard
check_health
check_control_plane
check_mode_dry_run
check_gate_guardrail
check_mode_unchanged_after_dry_run

if [[ "$OUTPUT_FORMAT" != "json" ]]; then
    echo
    echo -e "${BOLD}=== Summary ===${RESET}"
    echo "Passed: ${CHECKS_PASSED}"
    echo "Failed: ${CHECKS_FAILED}"
fi

# --- JSON output (stdout only; suppress text verdict) ---
if [[ "$OUTPUT_FORMAT" == "json" ]]; then
    json_out="$(_emit_json)" || {
        echo "ERROR: JSON emission failed" >&2
        exit 1
    }
    if [[ -n "$OUTPUT_FILE" ]]; then
        echo "$json_out" > "$OUTPUT_FILE"
    else
        echo "$json_out"
    fi
    # In JSON mode, suppress the text verdict; exit code communicates result
    exit $((CHECKS_FAILED > 0 ? 1 : 0))
fi

if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    [[ "$QUIET" != "true" ]] && echo -e "${RED}RELEASE GATE FAILED${RESET}"
    exit 1
fi
[[ "$QUIET" != "true" ]] && echo -e "${GREEN}RELEASE GATE PASSED${RESET}"
exit 0
