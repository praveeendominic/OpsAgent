"""Triage crew: one cheap LLM pass on top of the deterministic triage record."""
from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from opsagent.crews.common import agent_defaults, as_prompt_json, run_crew
from opsagent.schemas.triage import TriageNarrative, TriageRecord


@CrewBase
class TriageCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def event_analyst(self) -> Agent:
        return Agent(config=self.agents_config["event_analyst"], **agent_defaults())

    @task
    def confirm_triage(self) -> Task:
        return Task(config=self.tasks_config["confirm_triage"], output_pydantic=TriageNarrative)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)


def triage_inputs(record: TriageRecord) -> dict:
    c = record.classification
    return {
        "instance_id": record.instance.instance_id,
        "service": record.service or "unknown",
        "severity": record.severity,
        "reason": c.reason,
        "sub_reason": c.sub_reason,
        "confidence": c.confidence,
        "rationale": c.rationale,
        "evidence_json": as_prompt_json(record.evidence, max_chars=6000),
    }


def run_triage_crew(record: TriageRecord):
    return run_crew(TriageCrew().crew(), triage_inputs(record), TriageNarrative)
