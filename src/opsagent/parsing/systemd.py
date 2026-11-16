"""systemd unit lifecycle parsing (`systemd[1]: <unit>: ...` lines from the system log)."""
from __future__ import annotations

import re

from opsagent.parsing.common import size_to_mb, split_timestamp
from opsagent.schemas.triage import ServiceEvent

_SYSTEMD = re.compile(r"systemd\[\d+\]:\s*(?P<msg>.*)$")
_UNIT_PREFIX = re.compile(r"^(?P<unit>[A-Za-z0-9@_.:\\-]+\.(?:service|socket|timer|target|mount|scope|slice)):\s*(?P<msg>.*)$")

_MAIN_EXITED = re.compile(r"Main process exited, code=(?P<code>\w+), status=(?P<status>\S+)")
_FAILED = re.compile(r"Failed with result '(?P<result>[^']+)'")
_CONSUMED = re.compile(
    r"Consumed (?P<cpu>[\d.]+)(?P<cpu_unit>ms|s|min)? CPU time(?:, (?P<mem>[\d.]+[BKMGT]) memory peak)?"
    r"(?:, (?P<swap>[\d.]+[BKMGT]) memory swap peak)?"
)
_RESTART = re.compile(r"Scheduled restart job, restart counter is at (?P<n>\d+)")
_STARTED = re.compile(r"^Started (?P<unit>\S+?)\.?(?: - (?P<desc>.*?))?\.?$")
_STOPPED = re.compile(r"^Stopped (?P<unit>\S+?)\.?(?: - (?P<desc>.*?))?\.?$")


def _cpu_seconds(value: str, unit: str | None) -> float:
    n = float(value)
    if unit == "ms":
        return n / 1000.0
    if unit == "min":
        return n * 60.0
    return n


def parse_service_events(lines: list[str]) -> list[ServiceEvent]:
    """Extract systemd unit events from system log lines.

    Recognised messages (anything else from systemd is ignored):
    - `<unit>: Main process exited, code=killed, status=9/KILL`      -> killed (signal "9/KILL")
    - `<unit>: Failed with result 'signal'.`                         -> failed (result "signal")
    - `<unit>: Consumed 1.532s CPU time, 1.5G memory peak, ...`      -> consumed (cpu_seconds, memory_peak_mb)
    - `<unit>: Scheduled restart job, restart counter is at 2.`      -> restart_scheduled (restart_counter)
    - `Started <unit> - <description>.`                              -> started
    - `Stopped <unit> - <description>.`                              -> stopped
    """
    events: list[ServiceEvent] = []
    for raw in lines:
        if not isinstance(raw, str) or "systemd[" not in raw:
            continue
        ts, body = split_timestamp(raw)
        m = _SYSTEMD.search(body)
        if not m or ts is None:
            continue
        msg = m.group("msg").strip()

        unit: str | None = None
        um = _UNIT_PREFIX.match(msg)
        if um:
            unit, msg = um.group("unit"), um.group("msg").strip()

        if unit:
            mm = _MAIN_EXITED.search(msg)
            if mm:
                code, status = mm.group("code"), mm.group("status")
                if code == "killed":
                    events.append(ServiceEvent(timestamp=ts, unit=unit, event="killed", signal=status, detail=msg))
                else:
                    events.append(ServiceEvent(timestamp=ts, unit=unit, event="other", result=f"{code}/{status}", detail=msg))
                continue
            mm = _FAILED.search(msg)
            if mm:
                events.append(ServiceEvent(timestamp=ts, unit=unit, event="failed", result=mm.group("result"), detail=msg))
                continue
            mm = _CONSUMED.search(msg)
            if mm:
                events.append(
                    ServiceEvent(
                        timestamp=ts,
                        unit=unit,
                        event="consumed",
                        cpu_seconds=_cpu_seconds(mm.group("cpu"), mm.group("cpu_unit")),
                        memory_peak_mb=size_to_mb(mm.group("mem")) if mm.group("mem") else None,
                        detail=msg,
                    )
                )
                continue
            mm = _RESTART.search(msg)
            if mm:
                events.append(
                    ServiceEvent(timestamp=ts, unit=unit, event="restart_scheduled", restart_counter=int(mm.group("n")), detail=msg)
                )
                continue
            continue

        mm = _STARTED.match(msg)
        if mm:
            events.append(ServiceEvent(timestamp=ts, unit=mm.group("unit"), event="started", detail=mm.group("desc") or msg))
            continue
        mm = _STOPPED.match(msg)
        if mm:
            events.append(ServiceEvent(timestamp=ts, unit=mm.group("unit"), event="stopped", detail=mm.group("desc") or msg))
            continue

    return events


def restart_count(events: list[ServiceEvent]) -> int | None:
    """Highest restart counter seen across `restart_scheduled` events, or None if none was logged."""
    counters = [e.restart_counter for e in events if e.event == "restart_scheduled" and e.restart_counter is not None]
    return max(counters) if counters else None
