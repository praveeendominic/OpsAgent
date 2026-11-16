"""Offline tests for the run recorder's pure rendering helpers. No Streamlit import anywhere in this module."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from opsagent.ui import render

FIXTURE = Path(__file__).parent / "fixtures" / "run_sample.json"


def fake_run(running: bool = False) -> dict:
    steps = [
        {"name": "intake", "kind": "flow", "crew": None, "status": "done", "started_at": "2026-11-15T15:22:09.415+00:00",
         "t_start": 0.0, "t_end": 0.5, "duration_s": 0.5, "usage": {}, "cost_usd": 0.0, "error": None},
        {"name": "triage", "kind": "crew", "crew": "Triage", "status": "done", "started_at": "2026-11-15T15:22:09.9+00:00",
         "t_start": 0.5, "t_end": 31.7, "duration_s": 31.2,
         "usage": {"prompt_tokens": 6000, "completion_tokens": 400, "total_tokens": 6400, "successful_requests": 2},
         "cost_usd": 0.019, "error": None},
        {"name": "diagnose", "kind": "crew", "crew": "Diagnostics", "status": "running" if running else "error",
         "started_at": "2026-11-15T15:22:41.0+00:00", "t_start": 31.7, "t_end": None if running else 60.0,
         "duration_s": None if running else 28.3, "usage": {}, "cost_usd": 0.0,
         "error": None if running else "timeout"},
    ]
    return {
        "incident_id": "inc-test-0001", "event_id": "evt-1", "brand": "The Ark Enterprise", "model": "azure/gpt-4o",
        "started_at": "2026-11-15T15:22:09.412+00:00", "finished_at": None if running else "2026-11-15T15:23:10+00:00",
        "status": "running" if running else "error", "steps": steps, "artifacts": {}, "receipts": [],
        "timings": {"stage1": 48.2}, "totals": {"prompt_tokens": 6000, "completion_tokens": 400, "total_tokens": 6400,
                                                "cost_usd": 0.019, "llm_calls": 2}, "errors": [],
    }


def fake_card() -> dict:
    return {
        "type": "AdaptiveCard", "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "CRITICAL: orders-api OOM-killed", "weight": "Bolder", "size": "Large", "color": "Attention"},
            {"type": "ColumnSet", "columns": [
                {"width": "stretch", "items": [{"type": "FactSet", "facts": [
                    {"title": "Incident", "value": "inc-test-0001"},
                    {"title": "Instance", "value": "i-047b21366545ce721"},
                    {"title": "Severity", "value": "critical"},
                ]}]},
                {"width": "auto", "items": [{"type": "TextBlock", "text": "stage 1 in **48 s**", "isSubtle": True}]},
            ]},
            {"type": "Container", "style": "emphasis", "items": [
                {"type": "TextBlock", "text": "Immediate fix", "weight": "Bolder"},
                {"type": "TextBlock", "text": "sudo systemctl set-property orders-api.service MemoryMax=1500M",
                 "fontType": "Monospace", "wrap": True},
            ]},
            {"type": "ActionSet", "actions": [{"type": "Action.OpenUrl", "title": "Open trace", "url": "https://example.invalid/t/1"}]},
        ],
    }


def test_no_streamlit_imported():
    assert "streamlit" not in sys.modules


@pytest.mark.parametrize("value,expected", [(48.2, "48 s"), (245, "4 min 5 s"), (0, "0 s"), (59.6, "1 min 0 s"),
                                            (3725, "1 h 2 min"), (None, "–")])
def test_fmt_seconds(value, expected):
    assert render.fmt_seconds(value) == expected


def test_fmt_cost_and_tokens():
    assert render.fmt_cost(0.01234) == "$0.0123"
    assert render.fmt_cost(None) == "$0.0000"
    assert render.fmt_tokens(72580) == "72,580"


def test_card_html_contains_facts_and_monospace_command():
    out = render.card_html(fake_card())
    for title in ("Incident", "Instance", "Severity"):
        assert title in out
    assert "inc-test-0001" in out
    assert "<code" in out and "monospace" in out
    assert "MemoryMax=1500M" in out
    assert "#C0392B" in out  # attention colour on the headline
    assert "<strong>48 s</strong>" in out  # inline markdown bold
    assert "https://example.invalid/t/1" in out  # ActionSet link


def test_card_html_unwraps_teams_payload_and_escapes():
    payload = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                                                   "content": {"body": [{"type": "TextBlock", "text": "<b>x</b> & y"}]}}]}
    out = render.card_html(payload)
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in out


def test_steps_table_one_row_per_step_with_duration():
    rows = render.steps_table(fake_run())
    assert len(rows) == 3
    assert [r["step"] for r in rows] == ["intake", "triage", "diagnose"]
    assert rows[1]["duration_s"] == 31.2 and rows[1]["duration"] == "31 s"
    assert rows[1]["tokens"] == 6400 and rows[1]["crew"] == "Triage"
    assert rows[2]["status"] == "error" and rows[2]["error"] == "timeout"
    assert all("duration" in r and "start_s" in r and "kind" in r for r in rows)


def test_steps_table_running_step_gets_live_duration():
    now = datetime(2026, 11, 15, 15, 23, 41, tzinfo=timezone.utc)
    rows = render.steps_table(fake_run(running=True), now=now)
    assert rows[2]["status"] == "running"
    assert rows[2]["duration_s"] == 60.0
    assert rows[2]["duration"] == "1 min 0 s"


def test_timeline_html_marks_running_and_error():
    assert "oa-bar-running" in render.timeline_html(fake_run(running=True))
    assert "oa-bar-error" in render.timeline_html(fake_run())


def test_run_label_contains_incident_id_and_status():
    label = render.run_label(fake_run())
    assert "inc-test-0001" in label
    assert "error" in label
    assert label.count("·") == 2


def test_fixture_matches_schema_and_renders():
    run = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for key in ("incident_id", "event_id", "brand", "model", "started_at", "finished_at", "status", "steps", "artifacts",
                "receipts", "timings", "totals", "errors"):
        assert key in run
    assert run["brand"] == "The Ark Enterprise"
    assert run["timings"]["stage1"] < run["timings"]["stage2"]
    rows = render.steps_table(run)
    assert len(rows) == len(run["steps"]) >= 3
    assert "inc-20261115-152207-oom-047b21" in render.run_label(run)
    for name in ("triage", "diagnosis", "code_correlation", "package_stage1", "package_stage2", "kb_record"):
        assert name in run["artifacts"]
    card = render.package_card(run["artifacts"]["package_stage1"])
    html_out = render.card_html(card)
    assert "orders-api" in html_out and "Time to stage 1" in html_out and "48 s" in html_out
    stage2 = render.card_html(render.package_card(run["artifacts"]["package_stage2"]))
    assert "<code" in stage2 and "MemoryHigh=1200M" in stage2 and "Root cause" in stage2
