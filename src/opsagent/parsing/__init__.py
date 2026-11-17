"""Deterministic parsing layer: turns a `raw-1.0` event into a `triage-1.0` record without any LLM involvement.

Modules:
- `oom`            kernel OOM-killer lines            -> OOMEvent
- `systemd`        systemd unit lifecycle lines       -> ServiceEvent
- `applog`         JSON application log lines         -> AppLogSummary (leak profile, top errors)
- `inventory`      config/instances.yaml              -> InstanceDetails, repository paths
- `classify`       rules over the evidence            -> Classification, Severity
- `triage_builder` wires everything                   -> TriageRecord
"""
from __future__ import annotations

from opsagent.parsing.applog import AppLogSummary, parse_app_log
from opsagent.parsing.classify import classify, severity
from opsagent.parsing.severity_policy import SeverityPolicy, SeverityPolicyError, get_policy, load_policy
from opsagent.parsing.inventory import load_inventory, lookup_instance, repository_for
from opsagent.parsing.oom import parse_oom_events
from opsagent.parsing.systemd import parse_service_events, restart_count
from opsagent.parsing.triage_builder import build_triage

__all__ = [
    "AppLogSummary",
    "build_triage",
    "classify",
    "load_inventory",
    "lookup_instance",
    "parse_app_log",
    "parse_oom_events",
    "parse_service_events",
    "repository_for",
    "restart_count",
    "severity",
    "SeverityPolicy",
    "SeverityPolicyError",
    "get_policy",
    "load_policy",
]
