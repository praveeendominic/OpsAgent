"""Phase 2 contracts (Self-Healing). Defined so the state and the UI can show them; not produced by the PoC Flow."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RemediationPlan(BaseModel):
    schema_version: Literal["remediation-plan-1.0"] = "remediation-plan-1.0"
    incident_id: str
    action: str
    parameters: dict = Field(default_factory=dict)
    dry_run: str = Field(description="the exact command or API call that would run")
    reversal: str = ""
    blast_radius: str = ""
    expires_at: datetime | None = None
    approved_by: str | None = None
    approval_state: Literal["pending", "approved", "declined", "expired"] = "pending"


class RemediationResult(BaseModel):
    schema_version: Literal["remediation-result-1.0"] = "remediation-result-1.0"
    incident_id: str
    action: str
    executed: bool
    verified: bool
    rolled_back: bool = False
    detail: str = ""
    finished_at: datetime | None = None
