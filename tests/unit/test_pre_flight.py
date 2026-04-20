"""Unit tests for the pre-flight safety check module."""

from unittest.mock import patch

from trading.execution.gate import LiveTradingLock
from trading.risk.pre_flight import (
    BlockedCode,
    CheckStatus,
    PreFlightCheck,
    PreFlightResult,
    run_pre_flight,
)


class TestCheckStatus:
    def test_pass_status_value(self):
        assert CheckStatus.PASS == "pass"

    def test_fail_status_value(self):
        assert CheckStatus.FAIL == "fail"

    def test_skip_status_value(self):
        assert CheckStatus.SKIP == "skip"


class TestBlockedCode:
    def test_config_key_missing_value(self):
        assert (
            BlockedCode.CONFIG_BINANCE_API_KEY_MISSING
            == "config:binance_api_key_missing"
        )

    def test_config_secret_missing_value(self):
        assert (
            BlockedCode.CONFIG_BINANCE_API_SECRET_MISSING
            == "config:binance_api_secret_missing"
        )

    def test_symbol_not_whitelisted_value(self):
        assert BlockedCode.SYMBOL_NOT_WHITELISTED == "symbol:not_whitelisted"

    def test_live_lock_enabled_value(self):
        assert BlockedCode.LIVE_TRADING_LOCK_ENABLED == "live_trading_lock_enabled"

    def test_risk_global_pause_value(self):
        assert (
            BlockedCode.RISK_CIRCUIT_BREAKER_GLOBAL_PAUSE
            == "risk:global_pause"
        )

    def test_risk_emergency_stop_value(self):
        assert (
            BlockedCode.RISK_CIRCUIT_BREAKER_EMERGENCY_STOP
            == "risk:emergency_stop"
        )


class TestPreFlightCheck:
    def test_check_fields(self):
        check = PreFlightCheck(
            code="config:binance_api_key",
            status=CheckStatus.PASS,
            message="BINANCE_API_KEY is configured",
        )
        assert check.code == "config:binance_api_key"
        assert check.status == CheckStatus.PASS
        assert check.message == "BINANCE_API_KEY is configured"


class TestRunPreFlight:
    def _run_with_keys(self, api_key: str, api_secret: str, **kwargs):
        """Run pre-flight with specified env var values (fully isolated)."""
        env = {"BINANCE_API_KEY": api_key, "BINANCE_API_SECRET": api_secret}
        with patch.dict("os.environ", env, clear=True):
            return run_pre_flight(**kwargs)

    def test_all_pass(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT", "ETHUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is True
        assert result.blocked_reason is None
        # 5 checks: api_key + api_secret + symbol + lock + risk
        assert len(result.checks) == 5

    def test_api_key_missing(self):
        result = self._run_with_keys(
            api_key="",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.CONFIG_BINANCE_API_KEY_MISSING
        failed = [c for c in result.checks if c.status == CheckStatus.FAIL]
        assert len(failed) == 1
        assert "BINANCE_API_KEY" in failed[0].message

    def test_api_secret_missing(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.CONFIG_BINANCE_API_SECRET_MISSING

    def test_symbol_not_whitelisted(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="DOGEUSDT",
            allowed_symbols=["BTCUSDT", "ETHUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.SYMBOL_NOT_WHITELISTED
        failed = [c for c in result.checks if c.status == CheckStatus.FAIL]
        assert any("DOGEUSDT" in c.message for c in failed)

    def test_symbol_whitelisted(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="ethusdt",  # lowercase — should be normalized
            allowed_symbols=["BTCUSDT", "ETHUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is True
        assert result.blocked_reason is None

    def test_lock_enabled(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=True, reason="Scheduled maintenance"),
            risk_state="normal",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.LIVE_TRADING_LOCK_ENABLED
        failed = [c for c in result.checks if c.status == CheckStatus.FAIL]
        assert any("maintenance" in c.message.lower() for c in failed)

    def test_lock_disabled(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is True

    def test_risk_state_global_pause(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="global_pause",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.RISK_CIRCUIT_BREAKER_GLOBAL_PAUSE

    def test_risk_state_emergency_stop(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="emergency_stop",
        )
        assert result.passed is False
        assert result.blocked_reason == BlockedCode.RISK_CIRCUIT_BREAKER_EMERGENCY_STOP

    def test_risk_state_normal_passes(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is True

    def test_risk_state_degraded_passes(self):
        # degraded is not a blocking state
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="degraded",
        )
        assert result.passed is True

    def test_risk_state_no_new_positions_passes(self):
        # no_new_positions is not a hard block in pre-flight (it's advisory in live context)
        # Pre-flight only blocks global_pause and emergency_stop
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="no_new_positions",
        )
        assert result.passed is True

    def test_first_failure_determines_blocked_reason(self):
        # API key missing AND symbol not whitelisted — API key is checked first
        result = self._run_with_keys(
            api_key="",
            api_secret="",
            symbol="DOGEUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        assert result.passed is False
        # First failing check is config:binance_api_key
        assert result.blocked_reason == BlockedCode.CONFIG_BINANCE_API_KEY_MISSING

    def test_checks_returned_in_order(self):
        result = self._run_with_keys(
            api_key="test_key",
            api_secret="test_secret",
            symbol="BTCUSDT",
            allowed_symbols=["BTCUSDT"],
            lock=LiveTradingLock(enabled=False),
            risk_state="normal",
        )
        codes = [c.code for c in result.checks]
        assert codes == [
            "config:binance_api_key",
            "config:binance_api_secret",
            "symbol:whitelist",
            "live_trading_lock",
            "risk:circuit_breaker",
        ]


class TestPreFlightResultAllPassed:
    def test_all_passed_returns_empty_checks(self):
        result = PreFlightResult.all_passed()
        assert result.passed is True
        assert result.blocked_reason is None
        assert result.checks == []
