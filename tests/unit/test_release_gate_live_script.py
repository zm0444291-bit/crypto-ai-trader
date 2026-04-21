"""Unit tests for scripts/release_gate_live.sh.

Uses RELEASE_GATE_TEST_MODE=1 so tests do not require a running backend.
"""

from __future__ import annotations

import json
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

    # -------------------------------------------------------------------------
    # JSON output mode
    # -------------------------------------------------------------------------

    def test_json_mode_returns_valid_json(self) -> None:
        """--format json produces parseable JSON with all required top-level fields."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--format", "json")
            # Should still exit 0 when all checks pass
            assert result.returncode == 0, (
                f"Expected 0, got {result.returncode}\nstderr: {result.stderr}"
            )
            # Entire stdout should be a valid JSON object
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"stdout is not valid JSON: {exc}\nstdout: {result.stdout}"
                ) from None
            # Required top-level fields
            assert "generated_at" in data, f"missing generated_at in {data.keys()}"
            assert data["mode"] == "paper_safe_gate", f"mode={data['mode']}"
            # summary
            assert "summary" in data
            s = data["summary"]
            assert isinstance(s["pass"], bool), f"summary.pass not bool: {s['pass']}"
            assert isinstance(s["allow_live_shadow"], bool)
            assert isinstance(s["allow_live_small_auto_dry_run"], bool)
            assert isinstance(s["blocked_reasons"], list)
            assert s["allow_live_shadow"] is True
            # checks
            assert "checks" in data
            checks = data["checks"]
            assert isinstance(checks, list)
            assert len(checks) == 8, f"Expected 8 checks, got {len(checks)}"
            codes = {c["code"] for c in checks}
            assert codes == {
                "ruff", "pytest", "dashboard_build",
                "health", "control_plane", "dry_run_preflight",
                "gate_guardrail", "mode_persistence",
            }
            for c in checks:
                assert c["status"] in ("pass", "fail", "warn"), f"bad status in {c}"
            # runtime_snapshot
            assert "runtime_snapshot" in data
            snap = data["runtime_snapshot"]
            for key in ("trade_mode", "lock_enabled", "transition_guard_to_live_small_auto",
                        "risk_state", "heartbeat_stale_alerting"):
                assert key in snap, f"missing {key} in runtime_snapshot"

    def test_json_mode_is_clean_no_text_leakage(self) -> None:
        """JSON mode output must not contain ANSI step/pass/fail markers."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--format", "json")
            assert result.returncode == 0
            # No step headings, check marks, or summary lines in stdout
            assert "[1/" not in result.stdout
            assert "[2/" not in result.stdout
            assert "✓" not in result.stdout
            assert "RELEASE GATE" not in result.stdout
            assert "Passed:" not in result.stdout
            assert "Failed:" not in result.stdout
            # stderr should be empty (no error messages)
            assert result.stderr == ""

    def test_json_output_to_file(self) -> None:
        """--output writes valid JSON to the specified file path."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            out_path = Path(tmp) / "gate_output.json"
            result = run_script(
                bindir,
                "--format", "json",
                "--output", str(out_path),
            )
            assert result.returncode == 0, (
                f"Expected 0, got {result.returncode}\nstderr: {result.stderr}"
            )
            assert out_path.exists(), "Output file was not created"
            data = json.loads(out_path.read_text())
            assert data["summary"]["pass"] is True
            assert len(data["checks"]) == 8

    def test_json_mode_dry_run_flag_backwards_compat(self) -> None:
        """--dry-run is accepted (no-op) and script still exits 0."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--format", "json", "--dry-run")
            assert result.returncode == 0
            data = json.loads(result.stdout)
            assert data["summary"]["pass"] is True

    def test_json_mode_invalid_format_exits_2(self) -> None:
        """--format with an invalid value exits 2 and prints an error."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--format", "xml")
            assert result.returncode == 2
            combined = result.stdout + result.stderr
            assert "ERROR" in combined or "error" in combined

    def test_quiet_flag_suppresses_text_output(self) -> None:
        """--quiet suppresses non-essential text in text mode."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = make_mock_bin(Path(tmp))
            result = run_script(bindir, "--format", "text", "--quiet")
            assert result.returncode == 0
            # In quiet mode, pass/fail markers should be suppressed
            assert "✓" not in result.stdout
            assert "RELEASE GATE PASSED" not in result.stdout
            # But the JSON (if any) or exit code still works
