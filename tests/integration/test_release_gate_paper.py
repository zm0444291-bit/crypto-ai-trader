"""Integration tests for scripts/release_gate_paper.sh

Tests the paper-safe release gate script success and failure paths.
Uses RELEASE_GATE_TEST_MODE=1 and config patching to avoid recursion.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "release_gate_paper.sh"


def make_mock_venv(tmpdir: Path) -> Path:
    """Create a mock .venv/bin with passing ruff/pytest/npm."""
    venv_bin = tmpdir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for cmd in ("ruff", "pytest", "npm"):
        bin_path = venv_bin / cmd
        bin_path.write_text("#!/bin/sh\nexit 0\n")
        bin_path.chmod(0o755)
    return venv_bin


def run_script(
    venv_bin: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the gate script with the given mock venv and optional extra env vars."""
    env = {
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", ""),
        "RELEASE_GATE_TEST_MODE": "1",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(GATE_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


class TestReleaseGateScript:
    """Test suite for release_gate_paper.sh behavior."""

    def test_script_is_executable(self) -> None:
        """Script must have the executable bit set."""
        assert GATE_SCRIPT.exists(), f"Script not found at {GATE_SCRIPT}"
        assert GATE_SCRIPT.stat().st_mode & 0o111, "Script is not executable"

    def test_success_path_all_commands_succeed(self) -> None:
        """When ruff, pytest, build, and security checks all pass → exit 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_bin = make_mock_venv(Path(tmpdir))
            result = run_script(venv_bin)

            assert result.returncode == 0, (
                f"Expected exit 0 when all mocks succeed.\n"
                f"Got {result.returncode}.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

    def test_security_config_live_mode_blocked(self) -> None:
        """Script detects live_small_auto default and exits non-zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_bin = make_mock_venv(Path(tmpdir))
            tmpdir_path = Path(tmpdir)

            bad_config = tmpdir_path / "app_bad.yaml"
            with open(REPO_ROOT / "config" / "app.yaml") as f:
                original = f.read()

            import yaml
            cfg = yaml.safe_load(original)
            cfg["app"]["default_trade_mode"] = "live_small_auto"

            with open(bad_config, "w") as f:
                yaml.dump(cfg, f)

            app_yaml_path = REPO_ROOT / "config" / "app.yaml"
            original_content = app_yaml_path.read_text()

            try:
                app_yaml_path.write_text(bad_config.read_text())
                result = run_script(venv_bin)
                assert result.returncode != 0, (
                    f"Expected non-zero exit when default_trade_mode is live_small_auto.\n"
                    f"Got {result.returncode}.\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )
            finally:
                app_yaml_path.write_text(original_content)

    def test_security_config_live_trading_enabled_true(self) -> None:
        """Script detects live_trading_enabled=true and exits non-zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_bin = make_mock_venv(Path(tmpdir))
            tmpdir_path = Path(tmpdir)

            bad_config = tmpdir_path / "app_live.yaml"
            with open(REPO_ROOT / "config" / "app.yaml") as f:
                original = f.read()

            import yaml
            cfg = yaml.safe_load(original)
            cfg["app"]["live_trading_enabled"] = True

            with open(bad_config, "w") as f:
                yaml.dump(cfg, f)

            app_yaml_path = REPO_ROOT / "config" / "app.yaml"
            original_content = app_yaml_path.read_text()

            try:
                app_yaml_path.write_text(bad_config.read_text())
                result = run_script(venv_bin)
                assert result.returncode != 0, (
                    f"Expected non-zero exit when live_trading_enabled is true.\n"
                    f"Got {result.returncode}.\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )
            finally:
                app_yaml_path.write_text(original_content)

    def test_security_config_exchanges_live_trading_enabled(self) -> None:
        """Script detects binance.live_trading_enabled=true and exits non-zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_bin = make_mock_venv(Path(tmpdir))
            tmpdir_path = Path(tmpdir)

            bad_config = tmpdir_path / "exchanges_live.yaml"
            with open(REPO_ROOT / "config" / "exchanges.yaml") as f:
                original = f.read()

            import yaml
            cfg = yaml.safe_load(original)
            cfg["exchanges"]["binance"]["live_trading_enabled"] = True

            with open(bad_config, "w") as f:
                yaml.dump(cfg, f)

            exchanges_path = REPO_ROOT / "config" / "exchanges.yaml"
            original_content = exchanges_path.read_text()

            try:
                exchanges_path.write_text(bad_config.read_text())
                result = run_script(venv_bin)
                assert result.returncode != 0, (
                    f"Expected non-zero exit when exchanges live_trading_enabled is true.\n"
                    f"Got {result.returncode}.\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )
            finally:
                exchanges_path.write_text(original_content)
