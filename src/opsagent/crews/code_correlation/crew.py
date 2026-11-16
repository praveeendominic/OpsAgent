"""Code Correlation crew: find the code behind the log line, analyse it, issue a code / infra / shared verdict."""
from __future__ import annotations

from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel, Field

from opsagent.config import PROJECT_ROOT
from opsagent.crews.common import agent_defaults, run_crew
from opsagent.schemas.code_correlation import CodeCorrelation, CodeLocation, RecentCommit
from opsagent.schemas.triage import TriageRecord
from opsagent.tools.repo_tools import make_repo_tools


class LocatedCode(BaseModel):
    locations: list[CodeLocation] = Field(default_factory=list)
    entry_point: str | None = None
    unit_file_notes: str = ""
    tool_calls_used: int = 0


class CodeAnalysis(BaseModel):
    pattern: str = "none"
    findings: list[CodeLocation] = Field(default_factory=list)
    explanation: str = ""
    recent_commits: list[RecentCommit] = Field(default_factory=list)
    is_demo_fixture: bool = False


@CrewBase
class CodeCorrelationCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.repo_tools = make_repo_tools(repo_root)

    @agent
    def repo_navigator(self) -> Agent:
        return Agent(config=self.agents_config["repo_navigator"], tools=self.repo_tools, **agent_defaults())

    @agent
    def code_analyst(self) -> Agent:
        return Agent(config=self.agents_config["code_analyst"], tools=self.repo_tools, **agent_defaults())

    @agent
    def ownership_adjudicator(self) -> Agent:
        return Agent(config=self.agents_config["ownership_adjudicator"], **agent_defaults())

    @task
    def locate_code(self) -> Task:
        return Task(config=self.tasks_config["locate_code"], output_pydantic=LocatedCode)

    @task
    def analyse_code(self) -> Task:
        return Task(config=self.tasks_config["analyse_code"], output_pydantic=CodeAnalysis)

    @task
    def adjudicate(self) -> Task:
        return Task(config=self.tasks_config["adjudicate"], output_pydantic=CodeCorrelation)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)


def code_inputs(record: TriageRecord, repo_root: Path) -> dict:
    lp = record.evidence.leak_profile
    top = record.evidence.top_errors[0].message if record.evidence.top_errors else "order cache grew"
    try:
        repo_display = str(repo_root.relative_to(PROJECT_ROOT))
    except ValueError:
        repo_display = str(repo_root)
    return {
        "incident_id": record.incident_id,
        "service": record.service or "unknown",
        "repository": repo_display,
        "instance_id": record.instance.instance_id,
        "instance_type": record.instance.instance_type or "unknown type",
        "total_memory_mb": record.instance.total_memory_mb or "unknown",
        "slope_mb_per_min": f"{lp.slope_mb_per_min:.0f}" if lp else "unknown",
        "peak_rss_mb": f"{lp.peak_rss_mb:.0f}" if lp else "unknown",
        "top_error": top.replace("{", "(").replace("}", ")"),
    }


def run_code_correlation_crew(record: TriageRecord, repo_root: Path):
    run = run_crew(CodeCorrelationCrew(repo_root).crew(), code_inputs(record, repo_root), CodeCorrelation)
    if run.output is not None:
        cc: CodeCorrelation = run.output
        cc.event_id, cc.incident_id = record.event_id, record.incident_id
        if not cc.repository:
            cc.repository = code_inputs(record, repo_root)["repository"]
        seen: set[str] = set()
        cc.recent_commits = [c for c in cc.recent_commits if not (c.sha in seen or seen.add(c.sha))]
    return run
