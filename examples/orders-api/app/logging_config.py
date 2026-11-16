"""Structured JSON logging for orders-api.

Every line carries exactly these keys:
    ts, level, service, host, pid, msg, rss_mb, held_mb, mem_available_pct

`rss_mb` is the process resident set size, `held_mb` is what the order cache believes it
holds and `mem_available_pct` is the host's available memory as a percentage. Memory
figures come from psutil when installed, otherwise from /proc on Linux, otherwise 0.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone

from app import SERVICE_NAME

try:  # optional dependency
    import psutil  # type: ignore
except Exception:  # pragma: no cover - depends on the environment
    psutil = None  # type: ignore


def _rss_mb() -> float:
    if psutil is not None:
        try:
            return round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass
    try:
        import resource  # Unix only

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB, macOS reports bytes.
        divisor = 1024 if sys.platform.startswith("linux") else 1024 * 1024
        return round(usage / divisor, 1)
    except Exception:
        pass
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return 0.0


def _mem_available_pct() -> float:
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return round(vm.available / vm.total * 100, 1)
        except Exception:
            pass
    try:
        total = available = None
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
        if total and available is not None:
            return round(available / total * 100, 1)
    except Exception:
        pass
    return 0.0


def _held_mb() -> float:
    try:
        from app.orders.cache import held_bytes

        return round(held_bytes() / (1024 * 1024), 1)
    except Exception:
        return 0.0


class JsonFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self._host = socket.gethostname()
        self._pid = os.getpid()

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "host": self._host,
            "pid": self._pid,
            "msg": record.getMessage(),
            "rss_mb": getattr(record, "rss_mb", None) or _rss_mb(),
            "held_mb": getattr(record, "held_mb", None) or _held_mb(),
            "mem_available_pct": getattr(record, "mem_available_pct", None) or _mem_available_pct(),
        }
        return json.dumps(line, separators=(",", ":"))


def configure_logging(level: str | None = None) -> logging.Logger:
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level_name)
    # uvicorn's own loggers should go through the same formatter
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    return logging.getLogger(SERVICE_NAME)


def memory_snapshot() -> dict[str, float]:
    return {"rss_mb": _rss_mb(), "held_mb": _held_mb(), "mem_available_pct": _mem_available_pct()}
