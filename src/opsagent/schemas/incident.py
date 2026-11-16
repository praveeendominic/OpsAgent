"""incident-package-1.0: what Incident Bridge sends. Stage 1 carries triage only; stage 2 carries everything."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from opsagent.schemas.code_correlation import CodeCorrelation
from opsagent.schemas.diagnosis import Diagnosis, Fix
from opsagent.schemas.triage import TriageRecord


class DeliveryReceipt(BaseModel):
    channel: Literal["teams", "email", "outbox", "xmatters"]
    stage: Literal["stage1", "stage2", "delay", "closure"]
    ok: bool
    detail: str = ""
    target: str | None = None
    sent_at: datetime
    artifact: str | None = Field(default=None, description="file written, when the channel is the outbox")


class IncidentPackage(BaseModel):
    schema_version: Literal["incident-package-1.0"] = "incident-package-1.0"
    incident_id: str
    event_id: str
    stage: Literal["stage1", "stage2"]
    severity: str
    service: str | None = None
    instance_id: str
    headline: str
    summary: str = Field(description="narrative paragraph; stage 1 uses the triage summary")
    triage: TriageRecord
    diagnosis: Diagnosis | None = None
    code_correlation: CodeCorrelation | None = None
    recommended_fix: Fix | None = None
    durable_fix: Fix | None = None
    timings: dict[str, float] = Field(default_factory=dict, description="seconds since alarm for each milestone")
    trace_url: str | None = None
    brand: str = "The Ark Enterprise"
    created_at: datetime
