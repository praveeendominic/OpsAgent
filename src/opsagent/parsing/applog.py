"""Application log parsing: one JSON object per line.

Expected keys (all optional except `msg`): ts, level, service, pid, msg, rss_mb, held_mb, mem_available_pct,
step_mb, interval_s. Lines that are not JSON objects (for example an elided `... (...) ...` placeholder) are
skipped and counted in `AppLogSummary.skipped_lines`.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime

from pydantic import BaseModel, Field

from opsagent.parsing.common import parse_iso
from opsagent.schemas.triage import LeakProfile, TopError

_ERROR_LEVELS = {"WARNING", "WARN", "ERROR", "CRITICAL", "FATAL"}
_RESTART_MARKERS = ("service started", "started", "starting", "boot")


class AppLogSummary(BaseModel):
    """What the deterministic app-log pass hands to the triage builder."""

    leak_profile: LeakProfile | None = None
    top_errors: list[TopError] = Field(default_factory=list)
    samples: int = 0
    service: str | None = None
    last_pid: int | None = None
    restarted: bool = False
    skipped_lines: int = 0


class _Record(BaseModel):
    ts: datetime | None = None
    level: str = "INFO"
    service: str | None = None
    pid: int | None = None
    msg: str = ""
    rss_mb: float | None = None
    held_mb: float | None = None
    mem_available_pct: float | None = None
    step_mb: float | None = None
    interval_s: float | None = None


def _to_record(obj: dict) -> _Record:
    ts_raw = obj.get("ts") or obj.get("timestamp") or obj.get("time")
    ts = parse_iso(ts_raw) if isinstance(ts_raw, str) else None

    def num(key: str) -> float | None:
        v = obj.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    pid = obj.get("pid")
    return _Record(
        ts=ts,
        level=str(obj.get("level", "INFO")).upper(),
        service=obj.get("service") if isinstance(obj.get("service"), str) else None,
        pid=int(pid) if isinstance(pid, int) and not isinstance(pid, bool) else None,
        msg=str(obj.get("msg") or obj.get("message") or ""),
        rss_mb=num("rss_mb"),
        held_mb=num("held_mb"),
        mem_available_pct=num("mem_available_pct"),
        step_mb=num("step_mb"),
        interval_s=num("interval_s"),
    )


def _parse_records(lines: list[str]) -> tuple[list[_Record], int]:
    records: list[_Record] = []
    skipped = 0
    for raw in lines:
        if not isinstance(raw, str):
            skipped += 1
            continue
        text = raw.strip()
        if not text.startswith("{"):
            skipped += 1
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(obj, dict):
            skipped += 1
            continue
        records.append(_to_record(obj))
    return records, skipped


def _runs_by_pid(records: list[_Record]) -> list[list[_Record]]:
    """Split records into consecutive runs sharing the same pid (records without a pid join the current run)."""
    runs: list[list[_Record]] = []
    current: list[_Record] = []
    current_pid: int | None = None
    for r in records:
        if r.pid is not None and current_pid is not None and r.pid != current_pid:
            runs.append(current)
            current = []
        if r.pid is not None:
            current_pid = r.pid
        current.append(r)
    if current:
        runs.append(current)
    return runs


def _leak_profile(run: list[_Record]) -> LeakProfile | None:
    samples = [r for r in run if r.rss_mb is not None and r.ts is not None]
    if len(samples) < 2:
        return None
    first = samples[0]
    peak = max(samples, key=lambda r: r.rss_mb)  # type: ignore[arg-type]
    minutes = (peak.ts - first.ts).total_seconds() / 60.0  # type: ignore[operator]
    growth = float(peak.rss_mb) - float(first.rss_mb)  # type: ignore[arg-type]
    slope = growth / minutes if minutes > 0 else 0.0

    pct_values = [r.mem_available_pct for r in run if r.mem_available_pct is not None]
    leak_start = next((r for r in run if "leak started" in r.msg.lower()), None)
    step_mb = leak_start.step_mb if leak_start else next((r.step_mb for r in run if r.step_mb is not None), None)
    interval_s = (
        leak_start.interval_s if leak_start else next((r.interval_s for r in run if r.interval_s is not None), None)
    )
    return LeakProfile(
        start=first.ts,  # type: ignore[arg-type]
        end=samples[-1].ts,  # type: ignore[arg-type]
        first_rss_mb=float(first.rss_mb),  # type: ignore[arg-type]
        peak_rss_mb=float(peak.rss_mb),  # type: ignore[arg-type]
        slope_mb_per_min=round(slope, 3),
        mem_available_pct_at_kill=pct_values[-1] if pct_values else None,
        samples=len(samples),
        step_mb=step_mb,
        interval_s=interval_s,
    )


def _top_errors(records: list[_Record], limit: int = 5) -> list[TopError]:
    groups: OrderedDict[str, TopError] = OrderedDict()
    for r in records:
        if r.level not in _ERROR_LEVELS or not r.msg:
            continue
        existing = groups.get(r.msg)
        if existing is None:
            groups[r.msg] = TopError(message=r.msg, count=1, level=r.level, last_seen=r.ts)
            continue
        existing.count += 1
        existing.level = r.level
        if r.ts is not None and (existing.last_seen is None or r.ts > existing.last_seen):
            existing.last_seen = r.ts
    ranked = sorted(
        groups.values(),
        key=lambda e: (-e.count, -(e.last_seen.timestamp() if e.last_seen else 0.0)),
    )
    return ranked[:limit]


def parse_app_log(lines: list[str]) -> AppLogSummary:
    """Summarise JSON application log lines.

    - `leak_profile`: built from the rss_mb samples of the longest-growing single-pid run that precedes a restart
      (a "service started" line or any pid change). Slope is (peak - first) / minutes between first and peak sample;
      `mem_available_pct_at_kill` is the last mem_available_pct reported by that pid; step_mb/interval_s come from
      the "gradual leak started" line when present. If no restart occurred, the single run is profiled anyway.
    - `top_errors`: WARNING/ERROR/CRITICAL lines grouped by message, top 5 by count with last_seen.
    - `samples`: number of JSON records parsed; `skipped_lines`: non-JSON lines ignored.
    - `service`/`last_pid`: from the first/last record; `restarted`: True when a new pid took over.
    """
    records, skipped = _parse_records(lines)
    summary = AppLogSummary(samples=len(records), skipped_lines=skipped)
    if not records:
        return summary

    summary.service = next((r.service for r in records if r.service), None)
    summary.last_pid = next((r.pid for r in reversed(records) if r.pid is not None), None)
    summary.top_errors = _top_errors(records)

    runs = _runs_by_pid(records)
    pids = {r.pid for r in records if r.pid is not None}
    restart_marker = any(
        r.msg.lower().startswith(_RESTART_MARKERS) and r.pid is not None and r is not records[0] for r in records
    )
    summary.restarted = len(pids) > 1 or (restart_marker and len(runs) > 1)

    candidates = runs[:-1] if summary.restarted and len(runs) > 1 else runs
    profiles = [p for p in (_leak_profile(run) for run in candidates) if p is not None]
    if profiles:
        summary.leak_profile = max(profiles, key=lambda p: p.peak_rss_mb - p.first_rss_mb)
    return summary
