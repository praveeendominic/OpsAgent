"""Offline tests for the deterministic parsing layer (raw-1.0 -> triage-1.0)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsagent.parsing import (
    build_triage,
    classify,
    lookup_instance,
    parse_app_log,
    parse_oom_events,
    parse_service_events,
    repository_for,
    restart_count,
    severity,
)
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EVENT = PROJECT_ROOT / "events" / "log_event.json"


@pytest.fixture(scope="module")
def event() -> RawEvent:
    return RawEvent.model_validate(json.loads(SAMPLE_EVENT.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------------------------- oom


def test_oom_event_from_sample(event: RawEvent) -> None:
    events = parse_oom_events(event.system_lines)
    assert len(events) == 1
    o = events[0]
    assert o.killed_pid == 4525
    assert o.killed_process == "python3"
    assert o.anon_rss_kb == 1600620
    assert o.total_vm_kb == 1850320
    assert o.file_rss_kb == 2752
    assert o.uid == 999
    assert o.cgroup == "/system.slice/orders-api.service"
    assert o.invoked_by == "python3"
    assert o.timestamp == datetime(2026, 11, 15, 15, 21, 23, 577718, tzinfo=UTC)
    assert o.raw and "Killed process 4525" in o.raw


def test_oom_syslog_prefix() -> None:
    lines = [
        "Nov 15 15:21:23 demo-host kernel: oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),"
        "task_memcg=/system.slice/worker.service,task=java,pid=777,uid=1000",
        "Nov 15 15:21:23 demo-host kernel: Out of memory: Killed process 777 (java) total-vm:4000000kB, "
        "anon-rss:3500000kB, file-rss:1000kB, shmem-rss:0kB, UID:1000 pgtables:8000kB oom_score_adj:0",
    ]
    events = parse_oom_events(lines)
    assert len(events) == 1
    o = events[0]
    assert o.killed_pid == 777
    assert o.killed_process == "java"
    assert o.anon_rss_kb == 3500000
    assert o.cgroup == "/system.slice/worker.service"
    assert o.invoked_by is None
    assert o.timestamp.tzinfo is not None
    assert o.timestamp.year == datetime.now(UTC).year
    assert (o.timestamp.month, o.timestamp.day, o.timestamp.hour, o.timestamp.minute, o.timestamp.second) == (
        11,
        15,
        15,
        21,
        23,
    )


def test_oom_ignores_unrelated_lines() -> None:
    assert parse_oom_events(["2026-11-15T15:21:23+00:00 host systemd[1]: Started foo.service - foo.", "", "junk"]) == []


# ----------------------------------------------------------------------------------------- systemd


def test_service_events_from_sample(event: RawEvent) -> None:
    events = parse_service_events(event.system_lines)
    by_type = {e.event: e for e in events}

    assert all(e.unit == "orders-api.service" for e in events)
    assert by_type["killed"].signal == "9/KILL"
    assert by_type["failed"].result == "signal"
    assert by_type["consumed"].memory_peak_mb == 1536
    assert by_type["consumed"].cpu_seconds == pytest.approx(1.532)
    assert by_type["restart_scheduled"].restart_counter == 2
    assert "started" in by_type
    assert by_type["started"].detail and "orders-api dummy service" in by_type["started"].detail
    assert restart_count(events) == 2


def test_restart_count_none_when_absent() -> None:
    assert restart_count([]) is None
    events = parse_service_events(["2026-11-15T15:21:28+00:00 host systemd[1]: Started x.service - x."])
    assert restart_count(events) is None


# ------------------------------------------------------------------------------------------ applog


def test_app_log_leak_profile(event: RawEvent) -> None:
    summary = parse_app_log(event.app_lines)
    lp = summary.leak_profile
    assert lp is not None
    assert lp.first_rss_mb == pytest.approx(20.6)
    assert lp.peak_rss_mb == pytest.approx(1554.6)
    assert 230 <= lp.slope_mb_per_min <= 245
    assert lp.mem_available_pct_at_kill == pytest.approx(1.4)
    assert lp.step_mb == 20
    assert lp.interval_s == 5.0
    assert lp.samples == 3
    assert summary.service == "orders-api"
    assert summary.last_pid == 4802
    assert summary.restarted is True
    assert summary.samples == 4


def test_app_log_ignores_elided_line(event: RawEvent) -> None:
    assert any(line.startswith("... (") for line in event.app_lines)
    summary = parse_app_log(event.app_lines)
    assert summary.skipped_lines == 1
    assert summary.samples == len(event.app_lines) - 1
    # the placeholder never shows up as a message anywhere
    assert all(not e.message.startswith("...") for e in summary.top_errors)


def test_app_log_top_errors(event: RawEvent) -> None:
    summary = parse_app_log(event.app_lines)
    messages = {e.message: e for e in summary.top_errors}
    assert set(messages) == {"gradual leak started", "order cache grew"}
    assert messages["order cache grew"].count == 1
    assert messages["order cache grew"].level == "WARNING"
    assert messages["order cache grew"].last_seen == datetime(2026, 11, 15, 15, 21, 18, 506000, tzinfo=UTC)
    assert len(summary.top_errors) <= 5


def test_app_log_empty() -> None:
    summary = parse_app_log([])
    assert summary.leak_profile is None
    assert summary.top_errors == []
    assert summary.samples == 0


# --------------------------------------------------------------------------------------- inventory


def test_lookup_instance_known() -> None:
    inst = lookup_instance("i-047b21366545ce721")
    assert inst.source == "inventory"
    assert inst.instance_type == "t3.small"
    assert inst.total_memory_mb == 2048
    assert inst.vcpus == 2
    assert inst.region == "ap-south-1"
    assert inst.app == "orders-api"
    assert inst.owner == "platform-oncall"
    assert "orders-api.service" in inst.units


def test_lookup_instance_unknown() -> None:
    inst = lookup_instance("i-doesnotexist", region="eu-west-1")
    assert inst.source == "unknown"
    assert inst.instance_id == "i-doesnotexist"
    assert inst.instance_type is None
    assert inst.region == "eu-west-1"


def test_repository_for() -> None:
    path = repository_for("orders-api")
    assert path is not None
    assert path.is_absolute()
    assert path == PROJECT_ROOT / "examples" / "orders-api"
    assert repository_for("nope") is None


# ---------------------------------------------------------------------------------------- classify


def test_classify_oom(event: RawEvent) -> None:
    evidence = Evidence(oom_events=parse_oom_events(event.system_lines))
    c = classify(event, evidence)
    assert (c.reason, c.sub_reason, c.confidence, c.rule) == ("memory", "process_oom_kill", "high", "oom_kill_in_system_log")
    assert severity(event, evidence, c) == "critical"


def test_classify_rapid_growth_without_oom(event: RawEvent) -> None:
    evidence = Evidence(leak_profile=parse_app_log(event.app_lines).leak_profile)
    c = classify(event, evidence)
    assert (c.reason, c.sub_reason, c.confidence) == ("memory", "rapid_growth", "medium")
    # mem_available 1.4 % < 5 % -> still critical
    assert severity(event, evidence, c) == "critical"


def test_classify_cpu_and_fallback(event: RawEvent) -> None:
    cpu_event = event.model_copy(update={"event_type": "cpu"})
    c = classify(cpu_event, Evidence())
    assert (c.reason, c.sub_reason, c.confidence, c.rule) == ("cpu", "sustained_high_cpu", "medium", "alarm_event_type")
    assert severity(cpu_event, Evidence(), c) == "warning"

    disk_event = event.model_copy(update={"event_type": "disk"})
    c = classify(disk_event, Evidence())
    assert (c.reason, c.sub_reason, c.confidence) == ("disk", "threshold_breach", "low")
    assert severity(disk_event, Evidence(), c) == "info"

    odd_event = event.model_copy(update={"event_type": "latency"})
    assert classify(odd_event, Evidence()).reason == "unknown"


# ------------------------------------------------------------------------------------ triage record


def test_build_triage_from_sample(event: RawEvent) -> None:
    now = datetime(2026, 11, 15, 15, 23, 30, tzinfo=UTC)
    rec = build_triage(event, incident_id="inc-0001", now=now)

    assert rec.schema_version == "triage-1.0"
    assert rec.event_id == event.event_id
    assert rec.incident_id == "inc-0001"
    assert rec.service == "orders-api"
    assert rec.owner == "platform-oncall"
    assert rec.instance.instance_type == "t3.small"
    assert rec.instance.total_memory_mb == 2048
    assert rec.classification.reason == "memory"
    assert rec.classification.sub_reason == "process_oom_kill"
    assert rec.classification.confidence == "high"
    assert rec.severity == "critical"
    assert rec.evidence.restart_count == 2
    assert len(rec.evidence.oom_events) == 1
    assert rec.evidence.leak_profile is not None
    assert any("elided placeholder" in n for n in rec.evidence.notes)
    assert rec.summary is None and rec.analyst_agrees is None and rec.analyst_note is None
    assert rec.created_at == now

    digest = rec.digest()
    assert "pid 4525" in digest
    assert "CRITICAL memory/process_oom_kill" in digest
    assert "service orders-api" in digest

    # round-trips through JSON (what the Flow persists)
    assert json.loads(rec.model_dump_json())["severity"] == "critical"
