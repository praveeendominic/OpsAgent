"""Helpers shared by the log parsers: leading-timestamp extraction and size parsing."""
from __future__ import annotations

import re
from datetime import UTC, datetime

# 2026-11-15T15:21:23.574468+00:00 | 2026-11-15T15:21:23Z | 2026-11-15 15:21:23
_ISO_PREFIX = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)\s+(?P<rest>.*)$"
)
# Nov 15 15:21:23 | Nov  5 15:21:23
_SYSLOG_PREFIX = re.compile(
    r"^(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<rest>.*)$"
)
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}

_SIZE_UNITS = {"B": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024}


def split_timestamp(line: str, *, now: datetime | None = None) -> tuple[datetime | None, str]:
    """Split a log line into (timestamp, remainder).

    Accepts an ISO-8601 timestamp with offset (as CloudWatch/journald emit) or a syslog-style
    `Mon DD HH:MM:SS` prefix. Syslog prefixes carry no year or zone: the current year and UTC are assumed.
    Returns (None, line) when no timestamp is recognised.
    """
    line = line.rstrip()
    m = _ISO_PREFIX.match(line)
    if m:
        ts = m.group("ts").replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(ts)
        except ValueError:
            return None, line
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed, m.group("rest")
    m = _SYSLOG_PREFIX.match(line)
    if m:
        year = (now or datetime.now(UTC)).year
        hh, mm, ss = (int(x) for x in m.group("time").split(":"))
        try:
            parsed = datetime(year, _MONTHS[m.group("mon")], int(m.group("day")), hh, mm, ss, tzinfo=UTC)
        except ValueError:
            return None, line
        return parsed, m.group("rest")
    return None, line


def parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 string (with `Z` or offset) into an aware datetime; None on failure."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def size_to_mb(text: str) -> float | None:
    """Convert a systemd-style size (`1.5G`, `512M`, `0B`, `2048K`) to megabytes."""
    m = re.fullmatch(r"\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[BKMGT])?B?\s*", text or "")
    if not m:
        return None
    unit = m.group("unit") or "B"
    return round(float(m.group("num")) * _SIZE_UNITS[unit], 3)
