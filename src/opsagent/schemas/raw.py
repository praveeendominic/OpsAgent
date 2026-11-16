"""raw-1.0: the event the enricher puts on the queue. Exactly the shape of events/log_event.json."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AlarmInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    state: str = "ALARM"
    fired_at: datetime
    reason: str | None = None
    metric: str | None = None
    threshold: float | None = None


class LogGroupLines(BaseModel):
    model_config = ConfigDict(extra="allow")
    log_group: str = ""
    log_stream: str = ""
    lines: list[str] = Field(default_factory=list)


class RawLogs(BaseModel):
    model_config = ConfigDict(extra="allow")
    system: LogGroupLines | None = None
    app: LogGroupLines | None = None


class Window(BaseModel):
    start: datetime
    end: datetime


class RawEvent(BaseModel):
    """The only input the Flow accepts in the PoC."""

    model_config = ConfigDict(extra="allow")
    schema_version: Literal["raw-1.0"] = "raw-1.0"
    event_id: str
    event_type: str = "memory"
    provider: str = "aws"
    alarm: AlarmInfo
    instance_id: str
    region: str | None = None
    window: Window
    logs: RawLogs = Field(default_factory=RawLogs)

    @property
    def system_lines(self) -> list[str]:
        return list(self.logs.system.lines) if self.logs.system else []

    @property
    def app_lines(self) -> list[str]:
        return list(self.logs.app.lines) if self.logs.app else []
