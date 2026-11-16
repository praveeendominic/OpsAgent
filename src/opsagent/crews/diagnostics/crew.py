"""Diagnostics crew: timeline -> root cause with citations -> ranked fixes. Reads only the triage evidence plus
the knowledge base; it never calls AWS."""
from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel, Field

from opsagent.crews.common import agent_defaults, as_prompt_json, run_crew
from opsagent.schemas.diagnosis import Citation, Diagnosis, RootCause, TimelineEntry
from opsagent.schemas.triage import TriageRecord
from opsagent.tools.kb_search import ClosedIncidentsTool, KBSearchTool


class TimelineDraft(BaseModel):
    timeline: list[TimelineEntry] = Field(default_factory=list)
    gaps: str = ""


class RootCauseDraft(BaseModel):
    root_cause: RootCause
    citations: list[Citation] = Field(default_factory=list)
    classification_agreement: str = "agreed"
    notes: str = ""


@CrewBase
class DiagnosticsCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def evidence_correlator(self) -> Agent:
        return Agent(config=self.agents_config["evidence_correlator"], **agent_defaults())

    @agent
    def rca_engineer(self) -> Agent:
        return Agent(config=self.agents_config["rca_engineer"], tools=[KBSearchTool(), ClosedIncidentsTool()],
                     **agent_defaults())

    @agent
    def remediation_advisor(self) -> Agent:
        return Agent(config=self.agents_config["remediation_advisor"], tools=[KBSearchTool()], **agent_defaults())

    @task
    def build_timeline(self) -> Task:
        return Task(config=self.tasks_config["build_timeline"], output_pydantic=TimelineDraft)

    @task
    def find_root_cause(self) -> Task:
        return Task(config=self.tasks_config["find_root_cause"], output_pydantic=RootCauseDraft)

    @task
    def recommend_fixes(self) -> Task:
        return Task(config=self.tasks_config["recommend_fixes"], output_pydantic=Diagnosis)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)


def diagnostics_inputs(record: TriageRecord) -> dict:
    lp = record.evidence.leak_profile
    return {
        "incident_id": record.incident_id,
        "severity": record.severity,
        "event_type": record.event_type,
        "instance_id": record.instance.instance_id,
        "instance_type": record.instance.instance_type or "unknown type",
        "total_memory_mb": record.instance.total_memory_mb or "unknown",
        "service": record.service or "unknown",
        "triage_summary": record.summary or record.digest(),
        "evidence_json": as_prompt_json(record.evidence, max_chars=9000),
        "reason": record.classification.reason,
        "sub_reason": record.classification.sub_reason,
        "slope_mb_per_min": f"{lp.slope_mb_per_min:.0f}" if lp else "unknown",
        "peak_rss_mb": f"{lp.peak_rss_mb:.0f}" if lp else "unknown",
        "restart_count": record.evidence.restart_count if record.evidence.restart_count is not None else "unknown",
    }


def resolve_citations(diagnosis: Diagnosis) -> list[str]:
    """Make every citation resolvable: a source the knowledge base does not know is replaced by the best matching
    chunk for that citation's title, and the change is noted. Returns the notes."""
    from opsagent.kb.store import get_store

    notes: list[str] = []
    try:
        store = get_store()
    except Exception as exc:  # noqa: BLE001
        return [f"citation check skipped: {exc}"]
    resolved: list[Citation] = []
    seen: set[str] = set()
    for c in diagnosis.citations:
        namespace = "incidents" if c.source.startswith("kb://incidents/") else "docs"
        try:
            hits = store.search(f"{c.title} {c.snippet or ''}".strip(), k=3, namespace=namespace)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"citation check failed for {c.source}: {exc}")
            resolved.append(c)
            continue
        exact = next((h for h in hits if h.source == c.source), None)
        if exact is None and c.source.startswith("kb://"):
            try:
                exact = next((h for h in store.search(c.source.replace("kb://", "").replace("#", " ").replace("/", " "), k=3,
                                                       namespace=namespace) if h.source == c.source), None)
            except Exception:  # noqa: BLE001
                exact = None
        if exact is None and hits:
            best = hits[0]
            notes.append(f"citation '{c.source}' not found in the knowledge base; replaced with '{best.source}'")
            c = Citation(title=best.title, source=best.source, snippet=c.snippet or best.text[:160])
        elif exact is not None and not c.snippet:
            c = Citation(title=c.title, source=c.source, snippet=exact.text[:160])
        if c.source not in seen:
            seen.add(c.source)
            resolved.append(c)
    diagnosis.citations = resolved
    return notes


def run_diagnostics_crew(record: TriageRecord):
    run = run_crew(DiagnosticsCrew().crew(), diagnostics_inputs(record), Diagnosis)
    if run.output is not None:
        d: Diagnosis = run.output
        d.event_id, d.incident_id = record.event_id, record.incident_id
        d.provider, d.event_type, d.severity = record.provider, record.event_type, record.severity
        notes = resolve_citations(d)
        if notes:
            d.notes = (d.notes + " " if d.notes else "") + "Citation check: " + "; ".join(notes)
    return run
