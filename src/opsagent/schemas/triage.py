"""triage-1.0: what the Triage step produces from a raw event. Built by deterministic parsers; the LLM only adds
`summary`, `analyst_agrees` and `analyst_note`."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from opsagent.schemas.raw import AlarmInfo, Window

Severity = Literal["critical", "warning", "info"]
Confidence = Literal["high", "medium", "low"]


class OOMEvent(BaseModel):
    timestamp: datetime
    killed_process: str
    killed_pid: int
    anon_rss_kb: int | None = None
    total_vm_kb: int | None = None
    file_rss_kb: int | None = None
    cgroup: str | None = None
    uid: int | None = None
    invoked_by: str | None = None
    raw: str | None = None


class ServiceEvent(BaseModel):
    timestamp: datetime
    unit: str
    event: Literal["killed", "failed", "consumed", "restart_scheduled", "started", "stopped", "other"]
    result: str | None = None
    signal: str | None = None
    restart_counter: int | None = None
    memory_peak_mb: float | None = None
    cpu_seconds: float | None = None
    detail: str | None = None


class LeakProfile(BaseModel):
    start: datetime
    end: datetime
    first_rss_mb: float
    peak_rss_mb: float
    slope_mb_per_min: float
    mem_available_pct_at_kill: float | None = None
    samples: int = 0
    step_mb: float | None = None
    interval_s: float | None = None


class TopError(BaseModel):
    message: str
    count: int = 1
    level: str = "ERROR"
    last_seen: datetime | None = None


class InstanceDetails(BaseModel):
    instance_id: str
    instance_type: str | None = None
    total_memory_mb: int | None = None
    vcpus: int | None = None
    swap_mb: int | None = None
    region: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    units: dict[str, dict] = Field(default_factory=dict)
    source: Literal["inventory", "aws", "unknown"] = "unknown"

    @property
    def app(self) -> str | None:
        return self.tags.get("app")

    @property
    def owner(self) -> str | None:
        return self.tags.get("owner")


class Classification(BaseModel):
    reason: Literal["memory", "cpu", "disk", "network", "unknown"]
    sub_reason: str
    confidence: Confidence
    rule: str
    rationale: str


class Evidence(BaseModel):
    oom_events: list[OOMEvent] = Field(default_factory=list)
    service_events: list[ServiceEvent] = Field(default_factory=list)
    leak_profile: LeakProfile | None = None
    top_errors: list[TopError] = Field(default_factory=list)
    restart_count: int | None = None
    notes: list[str] = Field(default_factory=list)


class TriageNarrative(BaseModel):
    """What the Event Analyst agent returns (output_pydantic)."""

    summary: str = Field(description="Two plain sentences an on-call engineer can read in five seconds.")
    analyst_agrees: bool = Field(description="True if the rule-based classification matches the evidence.")
    analyst_note: str = Field(default="", description="One sentence if you disagree or want to add a caveat; else empty.")


class TriageRecord(BaseModel):
    schema_version: Literal["triage-1.0"] = "triage-1.0"
    event_id: str
    incident_id: str
    provider: str = "aws"
    event_type: str
    alarm: AlarmInfo
    instance: InstanceDetails
    window: Window
    service: str | None = None
    owner: str | None = None
    evidence: Evidence
    classification: Classification
    severity: Severity
    summary: str | None = None
    analyst_agrees: bool | None = None
    analyst_note: str | None = None
    created_at: datetime

    def digest(self) -> str:
        """Short, safe text for cards, prompts and the knowledge base."""
        lp = self.evidence.leak_profile
        parts = [
            f"{self.severity.upper()} {self.classification.reason}/{self.classification.sub_reason} on {self.instance.instance_id}",
            f"service {self.service or 'unknown'}",
        ]
        if self.evidence.oom_events:
            o = self.evidence.oom_events[-1]
            rss = f"{o.anon_rss_kb // 1024} MB" if o.anon_rss_kb else "unknown RSS"
            parts.append(f"OOM killed {o.killed_process} pid {o.killed_pid} at {rss}")
        if lp:
            parts.append(f"leak {lp.slope_mb_per_min:.0f} MB/min, peak {lp.peak_rss_mb:.0f} MB")
        if self.evidence.restart_count is not None:
            parts.append(f"restart counter {self.evidence.restart_count}")
        return "; ".join(parts)
