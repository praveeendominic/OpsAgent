"""Offline end-to-end test of IncidentFlow: every crew and every channel is replaced by a canned stand-in, so this
checks the orchestration (order, concurrency join, persistence, recorder, de-duplication) without an LLM."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVENT = ROOT / "events" / "log_event.json"


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSAGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OPSAGENT_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("OPSAGENT_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "")
    monkeypatch.setenv("SMTP_HOST", "")
    from opsagent import config

    config.get_settings.cache_clear()
    yield config.get_settings()
    config.get_settings.cache_clear()


def _canned(monkeypatch):
    from opsagent.crews import common
    from opsagent.crews.code_correlation import crew as cc_crew
    from opsagent.crews.diagnostics import crew as diag_crew
    from opsagent.crews.incident_bridge import crew as ib_crew
    from opsagent.crews.knowledge import crew as kb_crew
    from opsagent.crews.triage import crew as tri_crew
    from opsagent.schemas import (
        Citation, CodeCorrelation, CodeLocation, DeliveryReceipt, Diagnosis, Fix, RootCause, TimelineEntry,
        TriageNarrative,
    )

    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200, "successful_requests": 1}

    def mk(output):
        return lambda *a, **k: common.CrewRun(output=output, usage=dict(usage), raw="")

    monkeypatch.setattr(tri_crew, "run_triage_crew", mk(TriageNarrative(summary="orders-api was OOM-killed. L2 gets an RCA shortly.",
                                                                         analyst_agrees=True, analyst_note="")))
    diag = Diagnosis(
        timeline=[TimelineEntry(ts="2026-11-15T15:14:52Z", source="app log", what="leak started")],
        root_cause=RootCause(summary="orders-api holds every order in an in-process cache with no eviction.",
                             category="application_memory_leak", contributing=["no MemoryHigh/MemoryMax"], confidence="high"),
        citations=[Citation(title="systemd.resource-control: MemoryHigh", source="kb://systemd/resource-control#memoryhigh")],
        fixes=[Fix(horizon="immediate", owner="ops", action="set_unit_memory_limits", detail="drop-in MemoryHigh=1200M MemoryMax=1500M",
                   command="[Service]\nMemoryHigh=1200M\nMemoryMax=1500M"),
               Fix(horizon="durable", owner="dev", action="bound_cache", detail="LRU bound on the order cache")],
    )
    monkeypatch.setattr(diag_crew, "run_diagnostics_crew", mk(diag))
    cc = CodeCorrelation(verdict="shared", confidence=0.86, pattern="unbounded_growth",
                         locations=[CodeLocation(file="app/orders/cache.py", symbol="ORDER_CACHE", line=12)],
                         explanation="Module-level dict grows per order and never evicts.",
                         developer_action="Bound ORDER_CACHE with an LRU limit or TTL.")
    monkeypatch.setattr(cc_crew, "run_code_correlation_crew", mk(cc))
    monkeypatch.setattr(ib_crew, "run_incident_writer", mk(ib_crew.IncidentNarrative(headline="orders-api OOM-killed by unbounded cache",
                                                                                     summary="Narrative paragraph.")))
    monkeypatch.setattr(kb_crew, "run_librarian", mk(kb_crew.KBDraft(root_cause_summary="Unbounded order cache leak.",
                                                                     tags=["oom-kill", "cache-leak"], search_phrases=["orders-api oom"])))

    import importlib

    deliver_mod = importlib.import_module("opsagent.notify.deliver")

    def fake_deliver(pkg, settings=None):
        return [DeliveryReceipt(channel="outbox", stage=pkg.stage, ok=True, detail="test", sent_at=datetime.now(timezone.utc))]

    monkeypatch.setattr(deliver_mod, "deliver", fake_deliver)
    from opsagent.kb import incidents as inc_mod

    monkeypatch.setattr(inc_mod, "store_incident", lambda record: Path("stored.json"))


def test_flow_runs_end_to_end_offline(isolated_settings, monkeypatch):
    _canned(monkeypatch)
    from opsagent.flow.incident_flow import run_event

    result = run_event(EVENT, force=True)
    assert result["incident_id"].startswith("inc-")
    assert result["severity"] == "critical"
    t = result["timings"]
    for key in ("triage", "stage1", "diagnosis", "code_correlation", "stage2", "close"):
        assert key in t, f"missing milestone {key}: {t}"
    assert t["stage1"] <= t["stage2"] and t["stage2"] <= t["close"]
    assert result["errors"] == []
    assert result["totals"]["total_tokens"] == 1200 * 5  # triage, diagnostics, code, writer, librarian

    run = json.loads(Path(result["run_json"]).read_text(encoding="utf-8"))
    names = [s["name"] for s in run["steps"]]
    for expected in ("intake", "triage.parse", "triage.analyst", "page_stage1", "diagnose", "correlate_code",
                     "page_stage2.write", "page_stage2.deliver", "close.librarian", "close.store"):
        assert expected in names
    assert run["status"] == "done"
    assert set(run["artifacts"]) >= {"event", "triage", "diagnosis", "code_correlation", "package_stage1", "package_stage2", "kb_record"}
    assert run["artifacts"]["package_stage2"]["code_correlation"]["verdict"] == "shared"
    assert run["artifacts"]["kb_record"]["label"] == "pending"
    stages = [r["stage"] for r in run["receipts"]]
    assert stages == ["stage1", "stage2", "closure"]  # fake deliver per stage, then the ticket closure note
    assert run["receipts"][2]["channel"] == "servicenow" and run["receipts"][2]["ok"] is False  # not configured here


def test_second_run_is_deduplicated(isolated_settings, monkeypatch):
    _canned(monkeypatch)
    from opsagent.flow.incident_flow import run_event

    first = run_event(EVENT, force=True)
    second = run_event(EVENT, force=False)
    assert second.get("duplicate_of") == first["incident_id"]


def test_flow_degrades_when_a_crew_fails(isolated_settings, monkeypatch):
    _canned(monkeypatch)
    from opsagent.crews import common
    from opsagent.crews.diagnostics import crew as diag_crew

    monkeypatch.setattr(diag_crew, "run_diagnostics_crew",
                        lambda *a, **k: common.CrewRun(output=None, usage={}, raw="", error="boom"))
    from opsagent.flow.incident_flow import run_event

    result = run_event(EVENT, force=True)
    assert any(e.startswith("diagnose:") for e in result["errors"])
    assert "stage2" in result["timings"]  # the page still went out with a fallback diagnosis
    run = json.loads(Path(result["run_json"]).read_text(encoding="utf-8"))
    assert run["status"] == "done_with_errors"
    assert "Diagnosis unavailable" in run["artifacts"]["diagnosis"]["root_cause"]["summary"]
