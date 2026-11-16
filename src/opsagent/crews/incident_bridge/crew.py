"""Incident Bridge crew: the Incident Writer produces the stage 2 narrative. Delivery itself is deterministic code
in opsagent.notify."""
from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel, Field

from opsagent.crews.common import agent_defaults, as_prompt_json, run_crew
from opsagent.schemas.code_correlation import CodeCorrelation
from opsagent.schemas.diagnosis import Diagnosis
from opsagent.schemas.triage import TriageRecord


class IncidentNarrative(BaseModel):
    headline: str = Field(max_length=140)
    summary: str


@CrewBase
class IncidentBridgeCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def incident_writer(self) -> Agent:
        return Agent(config=self.agents_config["incident_writer"], **agent_defaults())

    @task
    def write_update(self) -> Task:
        return Task(config=self.tasks_config["write_update"], output_pydantic=IncidentNarrative)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)


def run_incident_writer(record: TriageRecord, diagnosis: Diagnosis | None, code: CodeCorrelation | None):
    inputs = {
        "incident_id": record.incident_id,
        "service": record.service or "unknown",
        "instance_id": record.instance.instance_id,
        "severity": record.severity,
        "digest": record.digest(),
        "diagnosis_json": as_prompt_json(diagnosis, max_chars=7000) if diagnosis else "not available",
        "code_json": as_prompt_json(code, max_chars=4000) if code else "not available",
    }
    return run_crew(IncidentBridgeCrew().crew(), inputs, IncidentNarrative)
