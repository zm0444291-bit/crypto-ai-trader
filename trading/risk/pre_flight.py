"""Pre-flight safety checks before transitioning to live_small_auto.

All checks are read-only — no state is modified. Failed checks return
machine-readable codes for consumption by the control plane API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from trading.execution.gate import LiveTradingLock
from trading.risk.state import RiskState

# ── Blocked reason codes ────────────────────────────────────────────────────────


class BlockedCode(StrEnum):
    """Machine-readable blocked reason codes for pre-flight failures.

    Used in PreFlightResult.blocked_reason and API responses so that both
    frontend dashboards and automated scripts can consume the result
    without parsing natural language.
    """

    # Configuration
    CONFIG_BINANCE_API_KEY_MISSING = "config:binance_api_key_missing"
    CONFIG_BINANCE_API_SECRET_MISSING = "config:binance_api_secret_missing"

    # Symbol
    SYMBOL_NOT_WHITELISTED = "symbol:not_whitelisted"

    # Lock
    LIVE_TRADING_LOCK_ENABLED = "live_trading_lock_enabled"

    # Risk
    RISK_CIRCUIT_BREAKER_GLOBAL_PAUSE = "risk:global_pause"
    RISK_CIRCUIT_BREAKER_EMERGENCY_STOP = "risk:emergency_stop"


# Static mapping: check code -> BlockedCode (risk_state handled at runtime)
_CODE_TO_BLOCKED: dict[str, BlockedCode] = {
    "config:binance_api_key": BlockedCode.CONFIG_BINANCE_API_KEY_MISSING,
    "config:binance_api_secret": BlockedCode.CONFIG_BINANCE_API_SECRET_MISSING,
    "symbol:whitelist": BlockedCode.SYMBOL_NOT_WHITELISTED,
    "live_trading_lock": BlockedCode.LIVE_TRADING_LOCK_ENABLED,
}

# ── Individual check result ─────────────────────────────────────────────────────


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class PreFlightCheck:
    """Result of a single pre-flight check."""

    code: str
    status: CheckStatus
    message: str


# ── Overall result ──────────────────────────────────────────────────────────────


@dataclass
class PreFlightResult:
    """Result of the full pre-flight check suite.

    Attributes:
        passed: True only when all applicable checks passed.
        blocked_reason: Machine-readable blocked code when passed=False.
            Always None when passed=True.
        checks: List of individual check results in execution order.
    """

    passed: bool
    blocked_reason: BlockedCode | None
    checks: list[PreFlightCheck]

    @classmethod
    def all_passed(cls) -> PreFlightResult:
        return cls(passed=True, blocked_reason=None, checks=[])


# ── Check functions ─────────────────────────────────────────────────────────────


def _check_config() -> list[PreFlightCheck]:
    """Verify required live-trading configuration is present."""
    checks: list[PreFlightCheck] = []

    api_key = os.environ.get("BINANCE_API_KEY", "").strip()
    if not api_key:
        checks.append(
            PreFlightCheck(
                code="config:binance_api_key",
                status=CheckStatus.FAIL,
                message="BINANCE_API_KEY is not set or empty",
            )
        )
    else:
        checks.append(
            PreFlightCheck(
                code="config:binance_api_key",
                status=CheckStatus.PASS,
                message="BINANCE_API_KEY is configured",
            )
        )

    api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()
    if not api_secret:
        checks.append(
            PreFlightCheck(
                code="config:binance_api_secret",
                status=CheckStatus.FAIL,
                message="BINANCE_API_SECRET is not set or empty",
            )
        )
    else:
        checks.append(
            PreFlightCheck(
                code="config:binance_api_secret",
                status=CheckStatus.PASS,
                message="BINANCE_API_SECRET is configured",
            )
        )

    return checks


def _check_symbol(symbol: str, allowed_symbols: list[str]) -> PreFlightCheck:
    """Verify the symbol is in the live-trading whitelist (case-insensitive)."""
    symbol_upper = symbol.upper()
    allowed_upper = [s.upper() for s in allowed_symbols]
    if symbol_upper in allowed_upper:
        return PreFlightCheck(
            code="symbol:whitelist",
            status=CheckStatus.PASS,
            message=f"{symbol} is in the allowed symbols list",
        )
    return PreFlightCheck(
        code="symbol:whitelist",
        status=CheckStatus.FAIL,
        message=f"{symbol} is not in the allowed symbols list: {allowed_symbols}",
    )


def _check_lock(lock: LiveTradingLock) -> PreFlightCheck:
    """Verify the live trading lock is not engaged."""
    if lock.enabled:
        reason = lock.reason or "live_trading_lock is enabled"
        return PreFlightCheck(
            code="live_trading_lock",
            status=CheckStatus.FAIL,
            message=reason,
        )
    return PreFlightCheck(
        code="live_trading_lock",
        status=CheckStatus.PASS,
        message="Live trading lock is not engaged",
    )


def _check_risk_state(risk_state: RiskState) -> PreFlightCheck:
    """Verify the risk subsystem is not in a blocked state."""
    if risk_state == "global_pause":
        return PreFlightCheck(
            code="risk:circuit_breaker",
            status=CheckStatus.FAIL,
            message="Risk circuit breaker: global_pause — live trading blocked",
        )
    if risk_state == "emergency_stop":
        return PreFlightCheck(
            code="risk:circuit_breaker",
            status=CheckStatus.FAIL,
            message="Risk circuit breaker: emergency_stop — live trading blocked",
        )
    return PreFlightCheck(
        code="risk:circuit_breaker",
        status=CheckStatus.PASS,
        message=f"Risk state is {risk_state}",
    )


# ── Runner ─────────────────────────────────────────────────────────────────────


def run_pre_flight(
    symbol: str,
    allowed_symbols: list[str],
    lock: LiveTradingLock,
    risk_state: RiskState,
) -> PreFlightResult:
    """Run all pre-flight checks.

    Args:
        symbol: Trading symbol to validate (e.g. "BTCUSDT").
        allowed_symbols: List of symbols permitted for live trading.
        lock: Current live trading lock state.
        risk_state: Current risk circuit-breaker state.

    Returns:
        PreFlightResult with passed=True only when all checks pass.
        When passed=False, blocked_reason contains a BlockedCode value.
    """
    checks: list[PreFlightCheck] = []
    blocked_reason: BlockedCode | None = None

    # 1. Config completeness
    config_checks = _check_config()
    checks.extend(config_checks)

    # 2. Symbol whitelist
    symbol_check = _check_symbol(symbol, allowed_symbols)
    checks.append(symbol_check)

    # 3. Live trading lock
    lock_check = _check_lock(lock)
    checks.append(lock_check)

    # 4. Risk circuit breaker
    risk_check = _check_risk_state(risk_state)
    checks.append(risk_check)

    # Aggregate: first failure determines blocked_reason
    for check in checks:
        if check.status == CheckStatus.FAIL:
            if check.code == "risk:circuit_breaker":
                blocked_reason = (
                    BlockedCode.RISK_CIRCUIT_BREAKER_GLOBAL_PAUSE
                    if risk_state == "global_pause"
                    else BlockedCode.RISK_CIRCUIT_BREAKER_EMERGENCY_STOP
                )
            else:
                blocked_reason = _CODE_TO_BLOCKED.get(check.code)
            break

    passed = blocked_reason is None and all(
        c.status in (CheckStatus.PASS, CheckStatus.SKIP) for c in checks
    )

    return PreFlightResult(
        passed=passed,
        blocked_reason=blocked_reason,
        checks=checks,
    )
