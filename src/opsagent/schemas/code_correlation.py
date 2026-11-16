"""code-correlation-1.0: the Code Correlation crew's verdict on whether the fault is code, infrastructure or shared."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CodeLocation(BaseModel):
    file: str = Field(description="path relative to the repository root")
    symbol: str | None = Field(default=None, description="function, class or module-level name")
    line: int | None = None
    excerpt: str | None = Field(default=None, description="at most 6 lines of code")
    why: str | None = Field(default=None, description="how this location explains the log line or the growth")


class RecentCommit(BaseModel):
    sha: str
    date: str
    message: str
    files: list[str] = Field(default_factory=list)


class CodeCorrelation(BaseModel):
    schema_version: Literal["code-correlation-1.0"] = "code-correlation-1.0"
    event_id: str = ""
    incident_id: str = ""
    repository: str = ""
    verdict: Literal["code", "infra", "shared", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0, description="0 to 1")
    pattern: Literal["unbounded_growth", "missing_eviction", "n_plus_one", "busy_loop", "resource_leak", "none"] = "none"
    locations: list[CodeLocation] = Field(default_factory=list)
    explanation: str = Field(description="Three sentences at most: what the code does, why it matches the evidence.")
    developer_action: str = Field(description="One concrete change a developer can make this week.")
    recent_commits: list[RecentCommit] = Field(default_factory=list)
    created_at: datetime | None = None
