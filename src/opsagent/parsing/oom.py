"""Kernel OOM-killer parsing.

A kill shows up in the system log as (at least) three kernel lines:

    kernel: python3 invoked oom-killer: gfp_mask=..., order=0, oom_score_adj=0
    kernel: oom-kill:constraint=CONSTRAINT_NONE,...,task_memcg=/system.slice/orders-api.service,task=python3,pid=4525,uid=999
    kernel: Out of memory: Killed process 4525 (python3) total-vm:1850320kB, anon-rss:1600620kB, file-rss:2752kB, ...

Only the `Killed process` line creates an OOMEvent; the two lines before it enrich it with the invoking process
and the cgroup the victim lived in.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from opsagent.parsing.common import split_timestamp
from opsagent.schemas.triage import OOMEvent

_INVOKED = re.compile(r"kernel:\s*(?P<proc>\S+) invoked oom-killer")
_CONSTRAINT = re.compile(r"kernel:\s*oom-kill:(?P<kv>.*)$")
_KILLED = re.compile(
    r"kernel:\s*(?:Out of memory: )?Killed process (?P<pid>\d+) \((?P<proc>[^)]+)\)(?P<rest>.*)$"
)
_KB_FIELD = re.compile(r"(?P<key>[a-z-]+):(?P<val>\d+)kB")
_UID_FIELD = re.compile(r"\bUID:(?P<uid>\d+)")


def _kv_pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_oom_events(lines: list[str]) -> list[OOMEvent]:
    """Extract every kernel OOM kill from system log lines.

    Lines may start with an ISO timestamp (with offset) or a syslog `Mon DD HH:MM:SS` prefix. The preceding
    `invoked oom-killer` and `oom-kill:constraint=` lines are attached to the next `Killed process` line when
    their pid matches (or the constraint line names no pid). Lines that are not kernel OOM lines are ignored.
    """
    events: list[OOMEvent] = []
    pending_invoker: str | None = None
    pending_constraint: dict[str, str] | None = None

    for raw in lines:
        if not isinstance(raw, str) or "kernel:" not in raw:
            continue
        ts, body = split_timestamp(raw)

        m = _INVOKED.search(body)
        if m:
            pending_invoker = m.group("proc")
            continue

        m = _CONSTRAINT.search(body)
        if m:
            pending_constraint = _kv_pairs(m.group("kv"))
            continue

        m = _KILLED.search(body)
        if not m:
            continue

        pid = int(m.group("pid"))
        rest = m.group("rest")
        kb = {f.group("key"): int(f.group("val")) for f in _KB_FIELD.finditer(rest)}
        uid_match = _UID_FIELD.search(rest)
        uid = int(uid_match.group("uid")) if uid_match else None

        cgroup: str | None = None
        if pending_constraint is not None:
            c_pid = pending_constraint.get("pid")
            if c_pid is None or c_pid == str(pid):
                cgroup = pending_constraint.get("task_memcg") or None
                if uid is None and pending_constraint.get("uid", "").isdigit():
                    uid = int(pending_constraint["uid"])

        if ts is None:
            # No usable timestamp at all: still record the kill, anchored at the epoch so the record validates.
            ts = datetime.fromtimestamp(0, tz=UTC)

        events.append(
            OOMEvent(
                timestamp=ts,
                killed_process=m.group("proc"),
                killed_pid=pid,
                anon_rss_kb=kb.get("anon-rss"),
                total_vm_kb=kb.get("total-vm"),
                file_rss_kb=kb.get("file-rss"),
                cgroup=cgroup,
                uid=uid,
                invoked_by=pending_invoker,
                raw=raw.strip(),
            )
        )
        pending_invoker = None
        pending_constraint = None

    return events
