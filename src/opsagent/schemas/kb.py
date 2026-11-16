"""kb-record-1.0: the closed incident as the Knowledge crew stores it, with the human label."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Label = Literal["pending", "accepted", "partially_correct", "wrong"]


class KBRecord(BaseModel):
    schema_version: Literal["kb-record-1.0"] = "kb-record-1.0"
    incident_id: str
    event_id: str
    provider: str = "aws"
    event_type: str
    service: str | None = None
    severity: str
    digest: str = Field(description="one-line triage digest")
    root_cause_summary: str
    root_cause_category: str = ""
    verdict: str = "unknown"
    code_location: str | None = None
    immediate_fix: str | None = None
    durable_fix: str | None = None
    outcome: str | None = Field(default=None, description="what happened after the fix, when known")
    citations: list[str] = Field(default_factory=list)
    label: Label = "pending"
    labelled_by: str | None = None
    labelled_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime

    def embedding_text(self) -> str:
        return "\n".join(
            [
                f"Incident {self.incident_id} ({self.event_type}, {self.severity}) on service {self.service or 'unknown'}",
                self.digest,
                f"Root cause: {self.root_cause_summary}",
                f"Verdict: {self.verdict}" + (f" at {self.code_location}" if self.code_location else ""),
                f"Immediate fix: {self.immediate_fix or 'n/a'}",
                f"Durable fix: {self.durable_fix or 'n/a'}",
                f"Label: {self.label}",
            ]
        )
