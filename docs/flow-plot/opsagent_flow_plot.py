"""Structural stub of the OpsAgent IncidentFlow, used only to render the
CrewAI built-in Flow.plot() diagram. Step names match the design document.
No crews are executed; every method is a placeholder."""
import os, shutil, sys
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from pydantic import BaseModel
from crewai.flow.flow import Flow, start, listen, router, and_, or_


class IncidentState(BaseModel):
    incident_id: str = ""
    severity: str = ""
    approved: bool = False


class IncidentFlow(Flow[IncidentState]):

    @start()
    def intake(self):
        """Accept raw-1.0 or classified-1.0 from SQS, dedupe, persist state."""

    @listen(intake)
    def watchdog(self):
        """Delay notice to L2 if the Flow has not paged by T+5 min."""

    @listen(intake)
    def triage(self):
        """Triage crew -> triage-1.0 (severity, event_type, confidence)."""

    @router(triage)
    def route_by_severity(self):
        if self.state.severity == "critical":
            return "critical"
        if self.state.severity == "warning":
            return "warning"
        return "info"

    @listen(or_("info", "warning"))
    def log_or_warn(self):
        """Info is logged; warning posts a note to the Teams channel."""

    @listen("critical")
    def page_stage1(self):
        """Incident Bridge crew: first page at ~T+60 s (Teams, email, xMatters)."""

    @listen("critical")
    def diagnose(self):
        """Diagnostics crew -> diagnosis-1.0 with doc citations."""

    @listen("critical")
    def correlate_code(self):
        """Code Correlation crew -> code-correlation-1.0 (code | infra | shared)."""

    @listen(and_(diagnose, correlate_code))
    def page_stage2(self):
        """Incident Bridge crew: RCA update with ownership verdict and proposed fix."""

    @listen(diagnose)
    def plan_remediation(self):
        """Self-Healing planner -> remediation-plan-1.0 with dry-run."""

    @router(plan_remediation)
    def approval_gate(self):
        if self.state.approved:
            return "approved"
        return "declined"

    @listen("approved")
    def execute_remediation(self):
        """Self-Healing executor: SSM / boto3, verify, roll back on failure."""

    @listen(and_(page_stage2, or_(execute_remediation, "declined")))
    def close(self):
        """Knowledge crew -> kb-record-1.0 with human label; closure update."""


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    html = Path(IncidentFlow().plot("opsagent_incident_flow.html", show=False))
    for f in html.parent.iterdir():
        shutil.copy(f, out_dir / f.name)
    print("generated:", sorted(p.name for p in out_dir.iterdir()))
