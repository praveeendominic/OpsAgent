"""Knowledge crew: the Incident Librarian distils the closed incident; the record is stored by opsagent.kb."""
from __future__ import annotations

from datetime import datetime, timezone

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel, Field

from opsagent.crews.common import agent_defaults, run_crew
from opsagent.schemas.code_correlation import CodeCorrelation
from opsagent.schemas.diagnosis import Diagnosis
from opsagent.schemas.kb import KBRecord
from opsagent.schemas.triage import TriageRecord


class KBDraft(BaseModel):
    root_cause_summary: str
    tags: list[str] = Field(default_factory=list)
    search_phrases: list[str] = Field(default_factory=list)


@CrewBase
class KnowledgeCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def incident_librarian(self) -> Agent:
        return Agent(config=self.agents_config["incident_librarian"], **agent_defaults())

    @task
    def write_record(self) -> Task:
        return Task(config=self.tasks_config["write_record"], output_pydantic=KBDraft)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)


def _code_location(code: CodeCorrelation | None) -> str | None:
    if not code or not code.locations:
        return None
    loc = code.locations[0]
    return f"{loc.file}:{loc.symbol}" if loc.symbol else loc.file


def run_librarian(record: TriageRecord, diagnosis: Diagnosis | None, code: CodeCorrelation | None):
    inputs = {
        "incident_id": record.incident_id,
        "service": record.service or "unknown",
        "event_type": record.event_type,
        "severity": record.severity,
        "digest": record.digest(),
        "root_cause": diagnosis.root_cause.summary if diagnosis else "not available",
        "verdict": code.verdict if code else "unknown",
        "code_location": _code_location(code) or "n/a",
        "immediate_fix": (diagnosis.immediate_fix.detail if diagnosis and diagnosis.immediate_fix else "n/a"),
        "durable_fix": (diagnosis.durable_fix.detail if diagnosis and diagnosis.durable_fix else "n/a"),
    }
    return run_crew(KnowledgeCrew().crew(), inputs, KBDraft)


def compose_kb_record(record: TriageRecord, diagnosis: Diagnosis | None, code: CodeCorrelation | None,
                      draft: KBDraft | None) -> KBRecord:
    """Deterministic assembly; the LLM draft only improves wording and tags."""
    summary = (draft.root_cause_summary if draft else None) or (diagnosis.root_cause.summary if diagnosis else record.digest())
    tags = list(dict.fromkeys((draft.tags if draft else []) + [record.event_type, record.classification.sub_reason,
                                                               record.service or "unknown-service"]))
    if draft and draft.search_phrases:
        summary = summary + " Search: " + "; ".join(draft.search_phrases)
    return KBRecord(
        incident_id=record.incident_id,
        event_id=record.event_id,
        provider=record.provider,
        event_type=record.event_type,
        service=record.service,
        severity=record.severity,
        digest=record.digest(),
        root_cause_summary=summary,
        root_cause_category=diagnosis.root_cause.category if diagnosis else "",
        verdict=code.verdict if code else "unknown",
        code_location=_code_location(code),
        immediate_fix=(diagnosis.immediate_fix.detail if diagnosis and diagnosis.immediate_fix else None),
        durable_fix=(diagnosis.durable_fix.detail if diagnosis and diagnosis.durable_fix else None),
        citations=[c.source for c in (diagnosis.citations if diagnosis else [])],
        tags=tags,
        created_at=datetime.now(timezone.utc),
    )
