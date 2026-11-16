"""Wire the parsers into a `triage-1.0` record. No LLM, no network: safe to run anywhere."""
from __future__ import annotations

from datetime import UTC, datetime

from opsagent.parsing.applog import parse_app_log
from opsagent.parsing.classify import classify, severity
from opsagent.parsing.inventory import lookup_instance
from opsagent.parsing.oom import parse_oom_events
from opsagent.parsing.systemd import parse_service_events, restart_count
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Evidence, TriageRecord


def _strip_unit_suffix(unit: str) -> str:
    return unit[: -len(".service")] if unit.endswith(".service") else unit


def build_triage(event: RawEvent, incident_id: str, now: datetime | None = None) -> TriageRecord:
    """Parse both logs, look up the instance, classify, and assemble the TriageRecord.

    `service` is the systemd unit name without `.service` when any unit event was seen, else the service named in
    the app log, else the instance's `app` tag. `owner` is the instance's `owner` tag. `summary`, `analyst_agrees`
    and `analyst_note` are left for the Event Analyst agent.
    """
    system_lines = event.system_lines
    app_lines = event.app_lines

    oom_events = parse_oom_events(system_lines)
    service_events = parse_service_events(system_lines)
    app = parse_app_log(app_lines)

    notes: list[str] = []
    if app.skipped_lines:
        plural = "s" if app.skipped_lines != 1 else ""
        notes.append(f"app log contains an elided placeholder line ({app.skipped_lines} non-JSON line{plural} skipped)")
    if not system_lines:
        notes.append("no system log lines in the event")
    if not app_lines:
        notes.append("no app log lines in the event")
    if app.restarted:
        notes.append(f"app log shows the service restarted (new pid {app.last_pid})")

    evidence = Evidence(
        oom_events=oom_events,
        service_events=service_events,
        leak_profile=app.leak_profile,
        top_errors=app.top_errors,
        restart_count=restart_count(service_events),
        notes=notes,
    )

    instance = lookup_instance(event.instance_id, event.region)
    if instance.source == "unknown":
        evidence.notes.append(f"instance {event.instance_id} not found in the inventory")

    unit = next((e.unit for e in service_events if e.unit), None)
    service = _strip_unit_suffix(unit) if unit else (app.service or instance.app)

    classification = classify(event, evidence)
    sev = severity(event, evidence, classification)

    return TriageRecord(
        event_id=event.event_id,
        incident_id=incident_id,
        provider=event.provider,
        event_type=event.event_type,
        alarm=event.alarm,
        instance=instance,
        window=event.window,
        service=service,
        owner=instance.owner,
        evidence=evidence,
        classification=classification,
        severity=sev,
        created_at=now or datetime.now(UTC),
    )
