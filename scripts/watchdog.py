"""Timeout watchdog + task flow monitor for the build pipeline.

Usage:
    from watchdog import run_with_watchdog, TaskTracker

    tracker = TaskTracker()
    result = run_with_watchdog(
        cmd, timeout=300,
        on_timeout=lambda: print("WATCHDOG: killing process"),
        tracker=tracker,
        task_name="Stage 3 回测",
        step="执行回测",
    )
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

# ─── Timeout Watchdog ────────────────────────────────────────────────────────

class TimeoutException(Exception):
    """Raised when a command exceeds its allotted time."""
    def __init__(self, seconds: int, task: str):
        self.seconds = seconds
        self.task = task
        super().__init__(f"WATCHDOG: 命令超过 {seconds}s 未完成 — {task}")


@dataclass
class WatchdogResult:
    ok: bool
    output: str
    exit_code: int | None
    duration_s: float
    timed_out: bool = False
    error_msg: str | None = None


def run_with_watchdog(
    cmd: str,
    timeout: int = 300,
    workdir: str | None = None,
    on_timeout: Callable[[], None] | None = None,
    task_name: str = "",
    step: str = "",
) -> WatchdogResult:
    """Run a shell command with a hard timeout. Returns (ok, output, exit_code, duration).

    timeout: max seconds before SIGKILL
    on_timeout: called synchronously before the process is killed
    """
    start = time.monotonic()
    timed_out = False
    output_parts: list[str] = []
    lock = threading.Lock()

    def _read_stream(src, dest_list, label=""):
        try:
            for line in iter(src.readline, ""):
                if not line:
                    break
                ts = datetime.now(UTC).strftime("%H:%M:%S")
                entry = f"[{ts}] {label} {line}" if label else f"[{ts}] {line}"
                with lock:
                    dest_list.append(entry)
        except ValueError:
            pass

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=workdir or os.getcwd(),
        preexec_fn=os.setsid,
    )

    stderr_stream = proc.stderr or proc.stdout

    # Stream output in background so we can see it live
    def _pump():
        for line in iter(stderr_stream.readline, ""):
            if not line:
                break
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            with lock:
                output_parts.append(f"[{ts}] {line.decode(errors='replace')}")

    pump_thread = threading.Thread(target=_pump, daemon=True)
    pump_thread.start()

    def _watchdog_target():
        nonlocal timed_out
        joined_timeout = min(timeout * 0.8, timeout - 10)  # warn at 80%
        time.sleep(joined_timeout)
        if proc.poll() is None:
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            with lock:
                output_parts.append(f"[{ts}] ⚠ WATCHDOG: 命令执行超过 {joined_timeout:.0f}s，仍在运行...")
            time.sleep(max(10, timeout - joined_timeout))

        if proc.poll() is None:
            timed_out = True
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                time.sleep(2)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
            if on_timeout:
                on_timeout()

    watchdog = threading.Thread(target=_watchdog_target, daemon=True)
    watchdog.start()

    proc.wait()
    duration = time.monotonic() - start

    # Collect final output
    pump_thread.join(timeout=5)
    with lock:
        full_output = "".join(output_parts)

    if timed_out:
        return WatchdogResult(
            ok=False,
            output=full_output,
            exit_code=None,
            duration_s=duration,
            timed_out=True,
            error_msg=f"命令超时（>{timeout}s）",
        )

    return WatchdogResult(
        ok=proc.returncode == 0,
        output=full_output,
        exit_code=proc.returncode,
        duration_s=duration,
        timed_out=False,
    )


# ─── Task Flow Tracker ──────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "⏳ pending"
    RUNNING = "🔄 running"
    DONE    = "✅ done"
    FAILED  = "❌ failed"
    SKIPPED = "⏭ skipped"


@dataclass
class TaskStep:
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None
    output_lines: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def elapsed(self) -> str:
        if self.started_at is None:
            return "—"
        end = self.finished_at or datetime.now(UTC)
        diff = (end - self.started_at).total_seconds()
        m, s = divmod(int(diff), 60)
        return f"{m}m {s}s"


class TaskTracker:
    """Tracks progress through a multi-step build pipeline."""

    def __init__(self, pipeline_name: str = "Pipeline"):
        self.pipeline_name = pipeline_name
        self.tasks: list[TaskStep] = []
        self._current: TaskStep | None = None

    def add_task(self, name: str, description: str = "") -> TaskStep:
        """Add a task to the pipeline (must be done before the pipeline starts)."""
        step = TaskStep(name=name, description=description)
        self.tasks.append(step)
        return step

    def start(self, name: str | None = None) -> None:
        """Mark a task as running (by name or takes the next pending one)."""
        if name:
            task = next((t for t in self.tasks if t.name == name), None)
        else:
            task = next((t for t in self.tasks if t.status == TaskStatus.PENDING), None)

        if task is None:
            print("⚠ Tracker: no pending task found")
            return

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        self._current = task
        ts = task.started_at.strftime("%H:%M:%S")
        print(f"[{ts}] ▶ {task.name} — {task.description}")
        self._render()

    def log(self, line: str) -> None:
        """Append a log line to the currently running task."""
        if self._current:
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            self._current.output_lines.append(f"[{ts}] {line}")

    def succeed(self, name: str | None = None) -> None:
        """Mark the named task (or current) as succeeded."""
        task = self._find_task(name)
        if task:
            if task.started_at is None:
                task.started_at = datetime.now(UTC)
            task.status = TaskStatus.DONE
            task.finished_at = datetime.now(UTC)
            task.duration_s = (task.finished_at - task.started_at).total_seconds()
            ts = task.finished_at.strftime("%H:%M:%S")
            print(f"[{ts}] ✓ {task.name} 完成（{task.elapsed}）")
            self._render()
            self._current = None

    def fail(self, name: str | None = None, reason: str = "") -> None:
        """Mark the named task (or current) as failed."""
        task = self._find_task(name)
        if task:
            if task.started_at is None:
                task.started_at = datetime.now(UTC)
            task.status = TaskStatus.FAILED
            task.finished_at = datetime.now(UTC)
            task.duration_s = (task.finished_at - task.started_at).total_seconds()
            task.error = reason
            ts = task.finished_at.strftime("%H:%M:%S")
            print(f"[{ts}] ✗ {task.name} 失败 — {reason}")
            self._render()
            self._current = None

    def skip(self, name: str | None = None) -> None:
        """Skip the named task (or current)."""
        task = self._find_task(name)
        if task:
            if task.started_at is None:
                task.started_at = datetime.now(UTC)
            task.status = TaskStatus.SKIPPED
            task.finished_at = datetime.now(UTC)
            ts = task.finished_at.strftime("%H:%M:%S")
            print(f"[{ts}] ⏭ {task.name} 跳过")
            self._render()
            self._current = None

    def _find_task(self, name: str | None) -> TaskStep | None:
        if name:
            return next((t for t in self.tasks if t.name == name), None)
        return self._current

    def _render(self) -> None:
        """Print a compact progress bar to stderr (doesn't pollute output capture)."""
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.status in (TaskStatus.DONE, TaskStatus.SKIPPED))
        running = sum(1 for t in self.tasks if t.status == TaskStatus.RUNNING)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)

        bar_len = 40
        filled = int(bar_len * done / max(total, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        pct = done / max(total, 1) * 100

        status_map = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "🔄",
            TaskStatus.DONE:    "✅",
            TaskStatus.FAILED:  "❌",
            TaskStatus.SKIPPED: "⏭",
        }

        sep_h = "+" + "-" * 40 + "+"
        lines = [""]
        lines.append(f"+- {self.pipeline_name} " + ("-" * 24) + "+")
        lines.append(f"| [{bar}] {pct:5.1f}% ({done}/{total} done) |")
        for t in self.tasks:
            icon = status_map[t.status]
            extra = f" ({t.elapsed})" if t.duration_s or t.status == TaskStatus.RUNNING else ""
            lines.append(f"|   {icon} {t.name}{extra}")
        lines.append(sep_h)
        sep = "\n".join(lines)

        # ANSI clear-line before reprinting
        clear = "\r\033[K"
        sys.stderr.write(f"{clear}{sep}\n")
        sys.stderr.flush()

    def summary(self) -> str:
        """Return a text summary of the pipeline run."""
        lines = [f"\n{'='*60}", f"  {self.pipeline_name} — 任务报告", f"{'='*60}"]
        for t in self.tasks:
            icon = {
                TaskStatus.DONE: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.SKIPPED: "⏭",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.PENDING: "⏳",
            }[t.status]
            lines.append(f"  {icon} {t.name}")
            if t.duration_s:
                lines.append(f"       耗时: {t.elapsed}")
            if t.error:
                lines.append(f"       错误: {t.error}")
        total_s = sum(t.duration_s or 0 for t in self.tasks)
        m, s = divmod(int(total_s), 60)
        lines.append(f"\n  总耗时: {m}m {s}s")
        done = sum(1 for t in self.tasks if t.status == TaskStatus.DONE)
        lines.append(f"  完成: {done}/{len(self.tasks)}")
        return "\n".join(lines)

    def run_task(
        self,
        name: str,
        cmd: str,
        workdir: str | None = None,
        timeout: int = 300,
        description: str = "",
    ) -> WatchdogResult:
        """Convenience: start + execute command + succeed/fail. Returns WatchdogResult."""
        self.start(name)

        if cmd.strip() == "skip" or cmd.strip() == "":
            self.skip(name)
            return WatchdogResult(ok=True, output="(skipped)", exit_code=None, duration_s=0)

        result = run_with_watchdog(
            cmd,
            timeout=timeout,
            workdir=workdir,
            on_timeout=lambda: self.log(f"⚠ 命令超时（>{timeout}s），已强制终止"),
            task_name=name,
        )

        # Append output lines to tracker
        for line in result.output.splitlines()[-50:]:
            self.log(line)

        if result.timed_out:
            self.fail(name, reason=f"超时（>{timeout}s）")
        elif not result.ok:
            self.fail(name, reason=f"exit code {result.exit_code}")
        else:
            self.succeed(name)

        return result


# ─── Convenience decorator / helper ────────────────────────────────────────

def watchdog(
    timeout: int = 300,
    task_name: str = "",
    workdir: str | None = None,
):
    """Decorator that wraps any shell-command function with watchdog + tracker.

    Usage:
        @watchdog(timeout=300, task_name="Stage 3 回测")
        def run_backtest():
            return run_with_watchdog("python scripts/run_backtest_stage3.py", timeout=300)
    """
    def decorator(fn: Callable[[], WatchdogResult]):
        def wrapper(*args, **kwargs) -> WatchdogResult:
            name = task_name or fn.__name__
            result = run_with_watchdog(
                cmd=fn(*args, **kwargs),
                timeout=timeout,
                workdir=workdir,
                task_name=name,
            )
            return result
        return wrapper
    return decorator
