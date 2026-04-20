"""Unit tests for scripts/release_gate_live.sh.

Uses RELEASE_GATE_TEST_MODE=1 so tests do not require a running backend.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "release_gate_live.sh"


def make_mock_bin(tmpdir: Path) -> Path:
    """Create mock command binaries used by the gate in test mode."""
    bindir = tmpdir / "bin"
    bindir.mkdir(parents=True)
    for cmd in ("ruff", "pytest", "npm"):
        p = bindir / cmd
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)
    return bindir


def run_script(
    bindir: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", ""),
        "RELEASE_GATE_TEST_MODE": "1",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(GATE_SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


class TestReleaseGateLiveScript:
    def test_script_exists_and_executable(self) -> None:
        assert GATE_SCRIPT.exists(), f"Script not found at {GATE_SCRIPT}"
        assert GATE_SCRIPT.stat().st_mode & 0o111, "Script is not executable"

    def test_help_flag_prints_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--help")
            assert result.returncode == 0
            assert "Usage:" in result.stdout
            assert "--api-url" in result.stdout
            assert "--symbol" in result.stdout

    def test_test_mode_success_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(
                bindir,
                "--api-url",
                "http://127.0.0.1:9999",
                "--symbol",
                "ETHUSDT",
            )
            assert result.returncode == 0, (
                "Expected success in test mode.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
            assert "RELEASE GATE PASSED" in result.stdout
            assert "API_URL=http://127.0.0.1:9999" in result.stdout
            assert "SYMBOL=ETHUSDT" in result.stdout

    def test_unknown_arg_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--unknown-flag")
            assert result.returncode != 0
            assert "Unknown argument" in (result.stdout + result.stderr)
