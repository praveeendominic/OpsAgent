"""Persisted Flow state. One instance per incident; CrewAI adds the `id` field."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from opsagent.schemas.code_correlation import CodeCorrelation
from opsagent.schemas.diagnosis import Diagnosis
from opsagent.schemas.incident import DeliveryReceipt, IncidentPackage
from opsagent.schemas.kb import KBRecord
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import TriageRecord


class IncidentState(BaseModel):
    event: RawEvent | None = None
    incident_id: str = ""
    severity: str = ""
    started_at: datetime | None = None
    alarm_at: datetime | None = None
    duplicate_of: str | None = None

    triage: TriageRecord | None = None
    diagnosis: Diagnosis | None = None
    code_correlation: CodeCorrelation | None = None
    package_stage1: IncidentPackage | None = None
    package_stage2: IncidentPackage | None = None
    kb_record: KBRecord | None = None

    receipts: list[DeliveryReceipt] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict, description="seconds since Flow start per milestone")
    errors: list[str] = Field(default_factory=list)
    run_dir: str = ""
    closed: bool = False
