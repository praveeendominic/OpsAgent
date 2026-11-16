"""IncidentFlow: the CrewAI Flow that takes one raw-1.0 event from alarm to a knowledge record.

    intake -> triage -> route_by_severity -+-> critical: page_stage1 | diagnose | correlate_code
                                           |             -> page_stage2 (and_) -> close
                                           +-> warning / info: log_or_warn -> close

Self-Healing (plan_remediation, approval_gate, execute_remediation) is phase 2 and only exists as a flagged stub.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crewai.flow.flow import Flow, and_, listen, or_, router, start
from crewai.flow.persistence import SQLiteFlowPersistence, persist

from opsagent.config import get_settings
from opsagent.flow.ids import find_duplicate, mark_closed, new_incident_id
from opsagent.flow.state import IncidentState
from opsagent.schemas.code_correlation import CodeCorrelation
from opsagent.schemas.diagnosis import Diagnosis, RootCause
from opsagent.schemas.incident import IncidentPackage
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import TriageRecord
from opsagent.tracing import RunRecorder


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IncidentFlow(Flow[IncidentState]):
    """One instance per incident. `recorder` and `repo_root` are runtime attributes, not persisted state."""

    def __init__(self, recorder: RunRecorder | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.recorder = recorder
        self._watchdog: threading.Timer | None = None
        self._t0 = time.perf_counter()
        self._stage2_done = threading.Event()

    # ------------------------------------------------------------------ helpers
    def _rec(self) -> RunRecorder:
        if self.recorder is None:
            self.recorder = RunRecorder(self.state.incident_id or "adhoc", self.state.event.event_id if self.state.event else "")
        return self.recorder

    def _elapsed(self) -> float:
        return round(time.perf_counter() - self._t0, 3)

    def _mark(self, name: str) -> None:
        self.state.timings[name] = self._elapsed()
        self._rec().milestone(name, self.state.timings[name])

    def _fail(self, step: str, error: str) -> None:
        self.state.errors.append(f"{step}: {error}")

    # ------------------------------------------------------------------ steps
    @start()
    def intake(self) -> str:
        rec = self._rec()
        rec.start_step("intake")
        if isinstance(self.state.event, dict):
            self.state.event = RawEvent.model_validate(self.state.event)
        ev = self.state.event
        if ev is None:
            raise ValueError("IncidentFlow needs state.event (a raw-1.0 event)")
        self.state.started_at = self.state.started_at or _now()
        self.state.alarm_at = ev.alarm.fired_at
        s = get_settings()
        self._watchdog = threading.Timer(s.watchdog_seconds, self._watchdog_fire)
        self._watchdog.daemon = True
        self._watchdog.start()
        rec.artifact("event", ev)
        rec.end_step("intake", output={"incident_id": self.state.incident_id, "event_id": ev.event_id})
        return self.state.incident_id

    @listen(intake)
    def triage(self) -> TriageRecord:
        from opsagent.crews.triage.crew import run_triage_crew
        from opsagent.parsing.triage_builder import build_triage

        rec = self._rec()
        rec.start_step("triage.parse")
        record = build_triage(self.state.event, self.state.incident_id)
        rec.end_step("triage.parse", output={"severity": record.severity, "classification": record.classification.model_dump(),
                                             "digest": record.digest()})
        rec.start_step("triage.analyst", kind="crew", crew="Triage")
        run = run_triage_crew(record)
        if run.output is not None:
            record.summary = run.output.summary
            record.analyst_agrees = run.output.analyst_agrees
            record.analyst_note = run.output.analyst_note or None
        else:
            record.summary = record.digest()
            self._fail("triage.analyst", run.error or "no output")
        rec.end_step("triage.analyst", output=run.output, usage=run.usage, error=run.error)
        self.state.triage = record
        self.state.severity = record.severity
        rec.artifact("triage", record)
        self._mark("triage")
        return record

    @router(triage)
    def route_by_severity(self) -> str:
        return self.state.severity or "info"

    # ---- warning / info ------------------------------------------------------
    @listen(or_("warning", "info"))
    def log_or_warn(self) -> str:
        rec = self._rec()
        rec.start_step("log_or_warn")
        note = f"{self.state.severity}: {self.state.triage.digest() if self.state.triage else 'no triage'}"
        rec.end_step("log_or_warn", output=note)
        return note

    # ---- critical: three listeners run concurrently -------------------------
    @listen("critical")
    def page_stage1(self) -> list:
        from opsagent.notify.deliver import deliver

        rec = self._rec()
        rec.start_step("page_stage1", kind="crew", crew="Incident Bridge")
        t = self.state.triage
        pkg = IncidentPackage(
            incident_id=self.state.incident_id, event_id=t.event_id, stage="stage1", severity=t.severity,
            service=t.service, instance_id=t.instance.instance_id,
            headline=f"{t.service or 'service'} on {t.instance.instance_id}: {t.classification.sub_reason.replace('_', ' ')}",
            summary=t.summary or t.digest(), triage=t, timings={"since_start": self._elapsed()}, created_at=_now(),
        )
        receipts = deliver(pkg)
        self.state.package_stage1 = pkg
        self.state.receipts.extend(receipts)
        for r in receipts:
            rec.receipt(r)
        rec.artifact("package_stage1", pkg)
        self._mark("stage1")
        rec.end_step("page_stage1", output=[r.model_dump(mode="json") for r in receipts])
        return receipts

    @listen("critical")
    def diagnose(self) -> Diagnosis:
        from opsagent.crews.diagnostics.crew import run_diagnostics_crew

        rec = self._rec()
        rec.start_step("diagnose", kind="crew", crew="Diagnostics")
        run = run_diagnostics_crew(self.state.triage)
        if run.output is None:
            self._fail("diagnose", run.error or "no output")
            diag = Diagnosis(event_id=self.state.triage.event_id, incident_id=self.state.incident_id,
                             root_cause=RootCause(summary="Diagnosis unavailable: " + (run.error or "crew failed"),
                                                  category="unknown", confidence="low"),
                             notes="fallback diagnosis written by the Flow", created_at=_now())
        else:
            diag = run.output
            diag.created_at = diag.created_at or _now()
        self.state.diagnosis = diag
        rec.artifact("diagnosis", diag)
        self._mark("diagnosis")
        rec.end_step("diagnose", output=diag, usage=run.usage, error=run.error)
        return diag

    @listen("critical")
    def correlate_code(self) -> CodeCorrelation:
        from opsagent.crews.code_correlation.crew import run_code_correlation_crew
        from opsagent.parsing.inventory import repository_for

        rec = self._rec()
        rec.start_step("correlate_code", kind="crew", crew="Code Correlation")
        t = self.state.triage
        app = (t.instance.tags.get("app") if t.instance else None) or t.service or ""
        repo = repository_for(app) if app else None
        if repo is None or not Path(repo).exists():
            cc = CodeCorrelation(event_id=t.event_id, incident_id=self.state.incident_id, repository=app, verdict="unknown",
                                 confidence=0.0, explanation=f"No repository mapped for app '{app}'.",
                                 developer_action="Map the app tag to a repository in config/instances.yaml.", created_at=_now())
            run_usage, err = {}, "no repository"
        else:
            run = run_code_correlation_crew(t, Path(repo))
            if run.output is None:
                self._fail("correlate_code", run.error or "no output")
                cc = CodeCorrelation(event_id=t.event_id, incident_id=self.state.incident_id, repository=str(repo), verdict="unknown",
                                     confidence=0.0, explanation="Code Correlation unavailable: " + (run.error or "crew failed"),
                                     developer_action="Re-run Code Correlation.", created_at=_now())
            else:
                cc = run.output
                cc.created_at = cc.created_at or _now()
            run_usage, err = run.usage, run.error
        self.state.code_correlation = cc
        rec.artifact("code_correlation", cc)
        self._mark("code_correlation")
        rec.end_step("correlate_code", output=cc, usage=run_usage, error=err)
        return cc

    @listen(and_(diagnose, correlate_code))
    def page_stage2(self) -> list:
        from opsagent.crews.incident_bridge.crew import run_incident_writer
        from opsagent.notify.deliver import deliver

        rec = self._rec()
        t, d, c = self.state.triage, self.state.diagnosis, self.state.code_correlation
        rec.start_step("page_stage2.write", kind="crew", crew="Incident Bridge")
        run = run_incident_writer(t, d, c)
        if run.output is not None:
            headline, summary = run.output.headline, run.output.summary
        else:
            self._fail("page_stage2.write", run.error or "no output")
            headline = f"{t.service or 'service'} on {t.instance.instance_id}: {d.root_cause.category if d else 'diagnosis pending'}"
            summary = (d.root_cause.summary if d else t.summary) or t.digest()
        rec.end_step("page_stage2.write", output=run.output, usage=run.usage, error=run.error)

        rec.start_step("page_stage2.deliver", kind="crew", crew="Incident Bridge")
        pkg = IncidentPackage(
            incident_id=self.state.incident_id, event_id=t.event_id, stage="stage2", severity=t.severity, service=t.service,
            instance_id=t.instance.instance_id, headline=headline[:140], summary=summary, triage=t, diagnosis=d,
            code_correlation=c, recommended_fix=d.immediate_fix if d else None, durable_fix=d.durable_fix if d else None,
            timings=dict(self.state.timings) | {"since_start": self._elapsed()}, created_at=_now(),
        )
        receipts = deliver(pkg)
        self.state.package_stage2 = pkg
        self.state.receipts.extend(receipts)
        for r in receipts:
            rec.receipt(r)
        rec.artifact("package_stage2", pkg)
        self._mark("stage2")
        self._stage2_done.set()
        if self._watchdog:
            self._watchdog.cancel()
        rec.end_step("page_stage2.deliver", output=[r.model_dump(mode="json") for r in receipts])
        return receipts

    @listen(or_(page_stage2, log_or_warn))
    def close(self) -> dict:
        from opsagent.crews.knowledge.crew import compose_kb_record, run_librarian
        from opsagent.kb.incidents import store_incident

        rec = self._rec()
        t, d, c = self.state.triage, self.state.diagnosis, self.state.code_correlation
        draft, usage, err = None, {}, None
        if self.state.severity == "critical":
            rec.start_step("close.librarian", kind="crew", crew="Knowledge")
            run = run_librarian(t, d, c)
            draft, usage, err = run.output, run.usage, run.error
            if err:
                self._fail("close.librarian", err)
            rec.end_step("close.librarian", output=draft, usage=usage, error=err)
        rec.start_step("close.store")
        record = compose_kb_record(t, d, c, draft)
        try:
            path = store_incident(record)
            stored = str(path)
        except Exception as exc:  # noqa: BLE001
            stored = f"not stored: {exc}"
            self._fail("close.store", str(exc))
        self.state.kb_record = record
        self.state.closed = True
        mark_closed(self.state.incident_id)
        if self._watchdog:
            self._watchdog.cancel()
        rec.artifact("kb_record", record)
        self._mark("close")
        rec.end_step("close.store", output={"stored": stored, "label": record.label})
        rec.finish("done" if not self.state.errors else "done_with_errors")
        return {"incident_id": self.state.incident_id, "kb_record": stored, "timings": self.state.timings,
                "errors": self.state.errors}

    # ------------------------------------------------------------------ watchdog
    def _watchdog_fire(self) -> None:
        if self._stage2_done.is_set() or self.state.severity != "critical":
            return
        try:
            from opsagent.notify.deliver import deliver_delay_notice

            t = self.state.triage
            receipts = deliver_delay_notice(self.state.incident_id, t.service if t else None, self.state.severity, self._elapsed())
            self.state.receipts.extend(receipts)
            for r in receipts:
                self._rec().receipt(r)
            self._mark("delay_notice")
        except Exception as exc:  # noqa: BLE001
            self._fail("watchdog", str(exc))


# ---------------------------------------------------------------------- entry point
def _warm_up_knowledge_base(recorder: RunRecorder) -> None:
    """Load the embedding model and the indexes once, on the main thread, before crews use them concurrently."""
    recorder.start_step("kb.warm_up")
    try:
        from opsagent.kb.store import get_store

        store = get_store()
        warm = getattr(store, "warm_up", None)
        if callable(warm):
            warm()
        else:
            store.search("warm up", k=1, namespace="docs")
        recorder.end_step("kb.warm_up", output={"docs": store.count("docs"), "incidents": store.count("incidents")})
    except Exception as exc:  # noqa: BLE001
        recorder.end_step("kb.warm_up", error=f"{type(exc).__name__}: {exc}")


def load_event(path: Path) -> RawEvent:
    return RawEvent.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def run_event(event_path: Path, force: bool = False) -> dict:
    """Prepare ids, de-duplicate, create the recorder and run the Flow. Returns a JSON-able summary."""
    s = get_settings()
    s.export_llm_env()
    event = load_event(event_path)
    dup = None if force else find_duplicate(event.event_id, event.instance_id, event.event_type)
    if dup:
        return {"duplicate_of": dup, "event_id": event.event_id, "message": "event de-duplicated; use --force to run anyway"}
    incident_id = new_incident_id(event.event_id, event.instance_id, event.event_type)
    recorder = RunRecorder(incident_id, event.event_id)
    _warm_up_knowledge_base(recorder)
    persistence = SQLiteFlowPersistence(str(s.flows_db))
    flow = IncidentFlow(recorder=recorder, persistence=persistence)
    try:
        flow.kickoff(inputs={"event": event.model_dump(mode="json"), "incident_id": incident_id,
                             "run_dir": str(recorder.dir)})
    except Exception as exc:  # noqa: BLE001
        recorder.end_step("flow", error=f"{type(exc).__name__}: {exc}")
        recorder.finish("failed")
        raise
    st = flow.state
    return {
        "incident_id": incident_id,
        "severity": st.severity,
        "timings": st.timings,
        "receipts": [r.model_dump(mode="json") for r in st.receipts],
        "errors": st.errors,
        "run_json": str(recorder.path),
        "outbox": str(s.outbox_path / incident_id),
        "totals": recorder.data["totals"],
    }
