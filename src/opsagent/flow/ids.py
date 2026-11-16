"""Incident ids and de-duplication, backed by a small SQLite table in the state directory."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opsagent.config import get_settings


def _conn(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS incidents (
               incident_id TEXT PRIMARY KEY, event_id TEXT, instance_id TEXT, event_type TEXT,
               created_at TEXT, status TEXT DEFAULT 'open')"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_incidents_event ON incidents(event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_incidents_inst ON incidents(instance_id, event_type, created_at)")
    return conn


def registry_path() -> Path:
    return get_settings().state_path / "incidents.db"


def find_duplicate(event_id: str, instance_id: str, event_type: str, window_minutes: int | None = None,
                   now: datetime | None = None) -> str | None:
    """Return the incident id this event duplicates, or None."""
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    window = window_minutes if window_minutes is not None else s.dedupe_window_minutes
    with _conn(registry_path()) as conn:
        row = conn.execute("SELECT incident_id FROM incidents WHERE event_id = ?", (event_id,)).fetchone()
        if row:
            return row[0]
        since = (now - timedelta(minutes=window)).isoformat()
        row = conn.execute(
            "SELECT incident_id FROM incidents WHERE instance_id = ? AND event_type = ? AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 1",
            (instance_id, event_type, since),
        ).fetchone()
        return row[0] if row else None


def new_incident_id(event_id: str, instance_id: str, event_type: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    with _conn(registry_path()) as conn:
        n = conn.execute("SELECT COUNT(*) FROM incidents WHERE incident_id LIKE ?", (f"inc-{day}-%",)).fetchone()[0]
        incident_id = f"inc-{day}-{n + 1:04d}"
        conn.execute("INSERT INTO incidents(incident_id, event_id, instance_id, event_type, created_at) VALUES (?,?,?,?,?)",
                     (incident_id, event_id, instance_id, event_type, now.isoformat()))
    return incident_id


def mark_closed(incident_id: str) -> None:
    with _conn(registry_path()) as conn:
        conn.execute("UPDATE incidents SET status = 'closed' WHERE incident_id = ?", (incident_id,))
