"""diagnosis-1.0: the Diagnostics crew's output. Evidence comes from triage; the crew adds timeline, root cause,
citations and ranked fixes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TimelineEntry(BaseModel):
    ts: str = Field(description="ISO-8601 timestamp")
    source: str = Field(description="app log, system log, alarm, metric")
    what: str


class RootCause(BaseModel):
    summary: str = Field(description="Two or three sentences stating the cause and the mechanism.")
    category: str = Field(description="e.g. application_memory_leak, undersized_instance, runaway_process, unknown")
    contributing: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class Citation(BaseModel):
    title: str
    source: str = Field(description="kb://... or https://... exactly as returned by the knowledge base tool")
    snippet: str | None = None


class Fix(BaseModel):
    horizon: Literal["immediate", "durable"]
    owner: Literal["ops", "dev"]
    action: str = Field(description="short id such as set_unit_memory_limits, resize_instance, bound_cache")
    detail: str
    command: str | None = Field(default=None, description="exact command or drop-in text when applicable")
    reversal: str | None = None


class Diagnosis(BaseModel):
    schema_version: Literal["diagnosis-1.0"] = "diagnosis-1.0"
    event_id: str = ""
    incident_id: str = ""
    provider: str = "aws"
    event_type: str = "memory"
    severity: str = "critical"
    timeline: list[TimelineEntry] = Field(default_factory=list)
    root_cause: RootCause
    citations: list[Citation] = Field(default_factory=list)
    fixes: list[Fix] = Field(default_factory=list)
    classification_agreement: Literal["agreed", "challenged"] = "agreed"
    notes: str = ""
    created_at: datetime | None = None

    @property
    def immediate_fix(self) -> Fix | None:
        return next((f for f in self.fixes if f.horizon == "immediate"), None)

    @property
    def durable_fix(self) -> Fix | None:
        return next((f for f in self.fixes if f.horizon == "durable"), None)
