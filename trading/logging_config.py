"""Structured logging configuration — JSON logs to file + console."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record to stdout/stderr.

    Fields: ts (ISO), level, logger, message, module, func, line.
    Extra fields passed via `extra` dict are included as-is.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        result: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        # Include extra fields (e.g. symbol, equity, risk_state)
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime",
            ):
                result[key] = value
        return json.dumps(result, default=str)


def setup_logging(
    level: int = logging.INFO,
    log_dir: str | Path | None = None,
    log_file: str = "trader.log",
    rotation_max_bytes: int = 10 * 1_024 * 1_024,  # 10 MB
    rotation_backup_count: int = 5,
) -> None:
    """Configure the root logger with JSON file handler + coloured console.

    Args:
        level: Minimum log level (default INFO).
        log_dir: Directory for log files. If None, no file logging.
        log_file: Name of the rotating log file.
        rotation_max_bytes: Max size per file before rotation.
        rotation_backup_count: Number of backup files to keep.
    """
    root = logging.getLogger()

    # Remove any pre-existing handlers (e.g. from basicConfig calls)
    for h in root.handlers[:]:
        root.removeHandler(h)

    handlers: list[logging.Handler] = []
    formatter = JsonFormatter()

    # ── Console (human-readable) ────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    handlers.append(console)

    # ── Rotating file ──────────────────────────────────────────────────────
    if log_dir is not None:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler: logging.Handler = RotatingFileHandler(
            filename=log_path / log_file,
            maxBytes=rotation_max_bytes,
            backupCount=rotation_backup_count,
        )
        file_handler.setLevel(logging.DEBUG)  # file gets everything
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers)

    # Silence overly verbose third-party loggers
    for noisy in ("httpx", "httpcore", "websockets", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info(
        "Logging configured: level=%s file=%s",
        logging.getLevelName(level),
        (Path(log_dir) / log_file) if log_dir else "(none)",
    )
