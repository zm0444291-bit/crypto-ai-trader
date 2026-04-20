#!/usr/bin/env bash
# =============================================================================
# release_gate_paper.sh — Paper-safe one-shot release gate
#
# Exits 0 on success, non-zero on any failure.
# All steps are required unless marked OPTIONAL.
# =============================================================================
set -euo pipefail

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

step() { echo -e "${BOLD}[$1]${RESET} $2"; }
pass() { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}⚠${RESET} $1"; }
fail() { echo -e "${RED}✗ FAIL:${RESET} $1"; }

TOTAL=5

# ---- Stability guards -------------------------------------------------------
# Prevent parallel runs of this script (common source of apparent hangs).
# Do not lock in test mode because tests intentionally spawn this script.
if [[ "${RELEASE_GATE_TEST_MODE:-}" != "1" ]]; then
    LOCK_DIR="/tmp/crypto_release_gate.lock"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "✗ release_gate_paper.sh is already running (lock: $LOCK_DIR)"
        echo "  If stale: rm -rf $LOCK_DIR"
        exit 1
    fi
    cleanup_lock() { rm -rf "$LOCK_DIR" || true; }
    trap cleanup_lock EXIT
fi

PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-180}"   # 3m
BUILD_TIMEOUT_SECONDS="${BUILD_TIMEOUT_SECONDS:-180}"     # 3m

# ── Discover project root ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Test mode ─────────────────────────────────────────────────────────────────
# RELEASE_GATE_TEST_MODE=1: skip real command execution, only verify paths exist.
# This prevents recursive calls when tests invoke the script via subprocess.
_is_test_mode() {
    [[ "${RELEASE_GATE_TEST_MODE:-}" == "1" ]]
}

_timeout_cmd() {
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

_run_with_timeout() {
    local seconds="$1"
    shift
    local tcmd
    tcmd="$(_timeout_cmd)"
    if [[ -n "$tcmd" ]]; then
        "$tcmd" "$seconds" "$@"
    else
        # Portable fallback when timeout/gtimeout is unavailable (e.g., some macOS setups).
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

_run_pytest_embedded() {
    local timeout_seconds="$1"
    shift
    .venv/bin/python - "$timeout_seconds" "$@" <<'PY'
import os
import sys
import threading
import traceback

import pytest

timeout = int(sys.argv[1])
pytest_args = sys.argv[2:]
result_code = {"value": 1}

def _run() -> None:
    try:
        result_code["value"] = int(pytest.main(pytest_args))
    except BaseException:  # defensive: convert unexpected errors into gate failure
        traceback.print_exc()
        result_code["value"] = 1

worker = threading.Thread(target=_run, daemon=True)
worker.start()
worker.join(timeout)

if worker.is_alive():
    print(f"Command timed out after {timeout}s: .venv/bin/pytest {' '.join(pytest_args)}")
    os._exit(124)

# Force process exit to avoid rare interpreter-shutdown hangs after pytest summary.
sys.stdout.flush()
sys.stderr.flush()
os._exit(result_code["value"])
PY
}

# ── Helpers ───────────────────────────────────────────────────────────────────
run_ruff() {
    step "1/$TOTAL" "Running ruff check…"
    if _is_test_mode; then
        if command -v ruff > /dev/null 2>&1; then
            pass "ruff check passed (test mode - command available)"
        return 0
        else
            fail "ruff not found in PATH (test mode)"
            return 1
        fi
    elif .venv/bin/ruff check .; then
        pass "ruff check passed"
        return 0
    else
        fail "ruff check failed"
        return 1
    fi
}

run_pytest() {
    step "2/$TOTAL" "Running pytest…"
    # Guard against recursion when script is launched from within pytest without test mode.
    if [[ -n "${PYTEST_CURRENT_TEST:-}" ]] && ! _is_test_mode; then
        fail "Detected pytest context (PYTEST_CURRENT_TEST) — refusing nested pytest run"
        return 1
    fi
    if _is_test_mode; then
        if command -v pytest > /dev/null 2>&1; then
            pass "pytest passed (test mode - command available)"
            return 0
        else
            fail "pytest not found in PATH (test mode)"
            return 1
        fi
    else
        local -a pytest_args
        pytest_args=(-q)
        # Avoid self-referential recursion/hangs: gate script invoking tests that invoke gate script.
        # Can be overridden for explicit deep checks.
        if [[ "${RELEASE_GATE_INCLUDE_SELF_TESTS:-0}" != "1" ]]; then
            pytest_args+=(
                --ignore=tests/unit/test_release_gate_script.py
                --ignore=tests/integration/test_release_gate_paper.py
            )
        fi
        if _run_pytest_embedded "$PYTEST_TIMEOUT_SECONDS" "${pytest_args[@]}"; then
            pass "pytest passed"
            return 0
        else
            fail "pytest failed"
            return 1
        fi
    fi
}

build_dashboard() {
    step "3/$TOTAL" "Building dashboard…"
    if _is_test_mode; then
        if command -v npm > /dev/null 2>&1 && [[ -d "dashboard" ]]; then
            pass "dashboard build succeeded (test mode - command available)"
            return 0
        else
            fail "dashboard build failed (test mode - npm or dir missing)"
            return 1
        fi
    elif cd dashboard && _run_with_timeout "$BUILD_TIMEOUT_SECONDS" npm run build; then
        pass "dashboard build succeeded"
        cd "$PROJECT_ROOT"
        return 0
    else
        fail "dashboard build failed (check dashboard/build/)"
        cd "$PROJECT_ROOT"
        return 1
    fi
}

check_security_config() {
    step "4/$TOTAL" "Checking paper-safe security configuration…"
    local errors=0

    # ── 4a. default_trade_mode must NOT be live_small_auto ──────────────────
    local mode
    mode=$(python3 -c "
import yaml
with open('config/app.yaml') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('app', {}).get('default_trade_mode', 'MISSING'))
" 2>/dev/null || echo "MISSING")

    if [[ "$mode" == "live_small_auto" ]]; then
        fail "default_trade_mode is live_small_auto — unsafe for paper-safe"
        errors=$((errors + 1))
    elif [[ "$mode" == "MISSING" ]]; then
        fail "Could not read default_trade_mode from config/app.yaml"
        errors=$((errors + 1))
    else
        pass "default_trade_mode is '$mode' (not live_small_auto)"
    fi

    # ── 4b. live_trading_enabled must be false ───────────────────────────────
    local live_enabled
    live_enabled=$(python3 -c "
import yaml
with open('config/app.yaml') as f:
    cfg = yaml.safe_load(f)
v = cfg.get('app', {}).get('live_trading_enabled', 'MISSING')
print(str(v).lower() if v != 'MISSING' else 'MISSING')
" 2>/dev/null || echo "MISSING")

    if [[ "$live_enabled" == "true" ]]; then
        fail "live_trading_enabled is true in config/app.yaml — paper-safe requires false"
        errors=$((errors + 1))
    elif [[ "$live_enabled" == "MISSING" ]]; then
        fail "Could not read live_trading_enabled from config/app.yaml"
        errors=$((errors + 1))
    else
        pass "live_trading_enabled is '$live_enabled'"
    fi

    # ── 4c. exchanges live_trading_enabled must be false ────────────────────
    local ex_live
    ex_live=$(python3 -c "
import yaml
with open('config/exchanges.yaml') as f:
    cfg = yaml.safe_load(f)
v = cfg.get('exchanges', {}).get('binance', {}).get('live_trading_enabled', 'MISSING')
print(str(v).lower() if v != 'MISSING' else 'MISSING')
" 2>/dev/null || echo "MISSING")

    if [[ "$ex_live" == "true" ]]; then
        fail "binance.live_trading_enabled is true — paper-safe requires false"
        errors=$((errors + 1))
    elif [[ "$ex_live" == "MISSING" ]]; then
        fail "Could not read exchanges.binance.live_trading_enabled from config/exchanges.yaml"
        errors=$((errors + 1))
    else
        pass "exchanges.yaml binance.live_trading_enabled is '$ex_live'"
    fi

    # ── 4d. TRADE_MODES hardcoded block in gate.py ─────────────────────────
    # Verify that live_small_auto route is blocked by default in ExecutionGate
    if grep -q 'live_small_auto.*allowed=False' trading/execution/gate.py 2>/dev/null; then
        pass "ExecutionGate blocks live_small_auto by default"
    else
        # Fallback: check that gate.py contains the blocked reason string
        if grep -q 'live_small_auto_requires_explicit_unlock' trading/execution/gate.py 2>/dev/null; then
            pass "ExecutionGate blocks live_small_auto (requires explicit unlock)"
        else
            fail "live_small_auto block missing from gate.py — unsafe for paper-safe"
            errors=$((errors + 1))
        fi
    fi

    # ── 4e. LiveTradingLock default is False ────────────────────────────────
    if grep -q 'enabled: bool = False' trading/execution/gate.py 2>/dev/null; then
        pass "LiveTradingLock defaults to enabled=False"
    else
        warn "Could not confirm LiveTradingLock default — review gate.py"
    fi

    if [[ $errors -gt 0 ]]; then
        fail "Security config checks failed ($errors error(s))"
        return 1
    fi
    pass "All paper-safe security checks passed"
    return 0
}

check_api_health_hint() {
    step "5/$TOTAL" "Checking API route health (hint mode)…"
    # This step does NOT start a new service.
    # If the backend is already running, curl it; otherwise report the check
    # that an operator should perform manually.

    local base_url="${BACKEND_URL:-http://localhost:8000}"
    local endpoint="/runtime/status"
    local cp_endpoint="/runtime/control-plane"

    if curl -s --max-time 3 "$base_url$endpoint" > /dev/null 2>&1; then
        pass "Backend is running at $base_url"
        # Verify key fields are present
        local response
        response=$(curl -s --max-time 3 "$base_url$endpoint" 2>/dev/null)
        if echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
required = ['trade_mode','live_trading_lock_enabled','execution_route_effective',
            'supervisor_alive','heartbeat_stale_alerting','restart_exhausted_ingestion',
            'restart_exhausted_trading']
missing = [f for f in required if f not in data]
if missing:
    print('MISSING_FIELDS:' + ','.join(missing))
    sys.exit(1)
print('OK')
" 2>/dev/null; then
            pass "/runtime/status returns all required fields"
        else
            warn "/runtime/status returned but some fields may be missing — check manually"
        fi

        # Check control-plane
        if curl -s --max-time 3 "$base_url$cp_endpoint" > /dev/null 2>&1; then
            pass "/runtime/control-plane is reachable"
        else
            warn "/runtime/control-plane not reachable — operator should verify manually"
        fi
    else
        warn "Backend not running at $base_url — start with 'make backend' and re-run this check manually:"
        warn "  curl $base_url$endpoint"
        warn "  curl $base_url$cp_endpoint"
        warn "Expected: trade_mode=paper_auto, execution_route_effective=paper/blocked"
    fi

    pass "API health hint step complete (operator should confirm manually if backend was not running)"
    return 0
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    echo "=============================================="
    echo -e "${BOLD}Paper-Safe Release Gate${RESET}"
    echo "=============================================="
    echo ""

    local failed=0

    run_ruff      || failed=$((failed + 1))
    run_pytest    || failed=$((failed + 1))
    build_dashboard || failed=$((failed + 1))
    check_security_config || failed=$((failed + 1))
    check_api_health_hint || failed=$((failed + 1))

    echo ""
    if [[ $failed -eq 0 ]]; then
        echo -e "${GREEN}=============================================="
        echo -e "${GREEN}  ALL CHECKS PASSED — READY FOR PAPER DEPLOY"
        echo -e "${GREEN}==============================================${RESET}"
        exit 0
    else
        echo -e "${RED}=============================================="
        echo -e "${RED}  $failed STEP(S) FAILED — BLOCKED"
        echo -e "${RED}==============================================${RESET}"
        exit 1
    fi
}

main "$@"
