"""Tests for the release_gate_paper.sh script.

Uses RELEASE_GATE_TEST_MODE=1 to prevent subprocess recursion.
Security config checks are tested by patching config files and verifying
the script correctly detects violations.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "release_gate_paper.sh"


@pytest.fixture
def script_env() -> dict[str, str]:
    """Environment with RELEASE_GATE_TEST_MODE=1 to prevent real command execution."""
    env = dict(os.environ)
    env["RELEASE_GATE_TEST_MODE"] = "1"
    return env


def run_script(env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT_PATH)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class TestReleaseGateScript:
    """Verify release_gate_paper.sh exits correctly and produces expected output."""

    def test_script_exists_and_executable(self):
        assert SCRIPT_PATH.exists(), f"Script not found at {SCRIPT_PATH}"
        assert os.access(SCRIPT_PATH, os.X_OK), f"Script is not executable: {SCRIPT_PATH}"

    def test_script_passes_with_current_config(self, script_env: dict[str, str]):
        """The script should exit 0 when all paper-safe checks pass."""
        result = run_script(script_env)
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
        assert result.returncode == 0, (
            f"release_gate_paper.sh exited {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
        assert "ALL CHECKS PASSED" in result.stdout, (
            f"Expected 'ALL CHECKS PASSED' in output.\nGot:\n{result.stdout}"
        )

    def test_script_fails_when_live_trading_enabled_true(self, script_env: dict[str, str]):
        """Script must exit non-zero when live_trading_enabled is true."""
        app_yaml = PROJECT_ROOT / "config" / "app.yaml"
        original = app_yaml.read_text()

        # Patch config to have live_trading_enabled: true
        patched = original.replace(
            "live_trading_enabled: false",
            "live_trading_enabled: true",
        )

        try:
            app_yaml.write_text(patched)
            result = run_script(script_env)
            assert result.returncode != 0, (
                f"Script should fail when live_trading_enabled is true.\n"
                f"Got exit {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        finally:
            app_yaml.write_text(original)

    def test_script_fails_when_default_trade_mode_is_live_small_auto(
        self, script_env: dict[str, str]
    ):
        """Script must exit non-zero when default_trade_mode is live_small_auto."""
        app_yaml = PROJECT_ROOT / "config" / "app.yaml"
        original = app_yaml.read_text()

        patched = original.replace(
            "default_trade_mode: paper_auto",
            "default_trade_mode: live_small_auto",
        )

        try:
            app_yaml.write_text(patched)
            result = run_script(script_env)
            assert result.returncode != 0, (
                f"Script should fail when default_trade_mode is live_small_auto.\n"
                f"Got exit {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        finally:
            app_yaml.write_text(original)

    def test_script_fails_when_exchanges_live_trading_enabled_true(
        self, script_env: dict[str, str]
    ):
        """Script must exit non-zero when binance.live_trading_enabled is true."""
        exchanges_yaml = PROJECT_ROOT / "config" / "exchanges.yaml"
        original = exchanges_yaml.read_text()

        patched = original.replace(
            "live_trading_enabled: false",
            "live_trading_enabled: true",
        )

        try:
            exchanges_yaml.write_text(patched)
            result = run_script(script_env)
            assert result.returncode != 0, (
                f"Script should fail when binance.live_trading_enabled is true.\n"
                f"Got exit {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        finally:
            exchanges_yaml.write_text(original)

    def test_script_fails_when_gate_blocks_removed(self, script_env: dict[str, str]):
        """Script must fail if ExecutionGate no longer blocks live_small_auto."""
        gate_path = PROJECT_ROOT / "trading" / "execution" / "gate.py"
        original = gate_path.read_text()

        patched = original.replace(
            'reason="live_small_auto_requires_explicit_unlock"',
            'reason="live_small_auto_allowed"',
        )

        try:
            gate_path.write_text(patched)
            result = run_script(script_env)
            assert result.returncode != 0, (
                f"Script should fail when ExecutionGate no longer blocks live_small_auto.\n"
                f"Got exit {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        finally:
            gate_path.write_text(original)
