"""Offline tests for the xMatters channel: a fake trigger URL + xM API records every request; no network."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from opsagent.config import Settings
from opsagent.notify import deliver, deliver_closure, deliver_delay_notice
from opsagent.notify import xmatters as xm
from opsagent.schemas.kb import KBRecord
from tests.test_notify import stage1_pkg, stage2_pkg  # noqa: F401 - fixtures

TRIGGER = "https://acme.xmatters.com/api/integration/1/functions/0a1b2c3d/triggers?apiKey=SECRET-KEY-123"


class _Resp:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")
        self.content = self.text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeXMatters:
    """Trigger URL answers 202 + requestId; events become visible to GET /events?requestId after `visible_after` polls."""

    def __init__(self, fail_status: int | None = None, visible_after: int = 0, visible: bool = True):
        self.calls: list[dict] = []
        self.events: dict[str, dict] = {}  # event uuid -> record
        self.by_request: dict[str, str] = {}
        self.fail_status = fail_status
        self.visible_after = visible_after
        self.visible = visible
        self._n = 0
        self._polls = 0

    def client_factory(self):
        fake = self

        class _Client:
            def __init__(self, *a, **k):
                fake.calls.append({"init": k})

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def post(self, url, json=None, params=None, **k):
                fake.calls.append({"method": "POST", "url": url, "json": json})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                if "/triggers" in url:
                    fake._n += 1
                    rid = f"req-{fake._n}"
                    uuid = f"evt-uuid-{fake._n}"
                    fake.events[uuid] = {"id": uuid, "eventId": str(5000 + fake._n), "status": "ACTIVE",
                                         "payload": json, "annotations": []}
                    fake.by_request[rid] = uuid
                    return _Resp(202, {"requestId": rid})
                if url.endswith("/annotations"):
                    uuid = url.rsplit("/", 2)[1]
                    fake.events[uuid]["annotations"].append(json["comment"])
                    return _Resp(201, {"id": f"ann-{len(fake.events[uuid]['annotations'])}"})
                if url.endswith("/api/xm/1/events"):
                    fake.events[json["id"]]["status"] = json["status"]
                    return _Resp(200, {"id": json["id"], "status": json["status"]})
                return _Resp(404, text="unknown endpoint")

            def get(self, url, params=None, **k):
                fake.calls.append({"method": "GET", "url": url, "params": params})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                fake._polls += 1
                uuid = fake.by_request.get((params or {}).get("requestId", ""))
                if not uuid or not fake.visible or fake._polls <= fake.visible_after:
                    return _Resp(200, {"count": 0, "total": 0, "data": []})
                e = fake.events[uuid]
                return _Resp(200, {"count": 1, "total": 1, "data": [{"id": e["id"], "eventId": e["eventId"], "status": e["status"]}]})

        return _Client


@pytest.fixture()
def xm_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        XMATTERS_TRIGGER_URL=TRIGGER,
        XMATTERS_USER="opsagent-key-id",
        XMATTERS_PASSWORD="not-a-real-secret",
        XMATTERS_RECIPIENTS="Platform On-call, dominic.ops",
    )


@pytest.fixture()
def trigger_only_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL=TRIGGER)


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeXMatters) -> None:
    monkeypatch.setattr(xm.httpx, "Client", fake.client_factory())


def _kb(pkg) -> KBRecord:
    return KBRecord(incident_id=pkg.incident_id, event_id=pkg.event_id, event_type="ec2.oom_kill", severity="critical",
                    digest="orders-api OOM-killed", root_cause_summary="unbounded in-process order cache",
                    verdict="shared", created_at=datetime.now(timezone.utc))


# ------------------------------------------------------------------------------------------------ settings
def test_settings_derive_base_url_and_enablement(xm_settings: Settings, trigger_only_settings: Settings, tmp_path: Path) -> None:
    assert xm_settings.xmatters_enabled and xm_settings.xmatters_api_enabled
    assert xm_settings.xmatters_base_url == "https://acme.xmatters.com"
    assert trigger_only_settings.xmatters_enabled and not trigger_only_settings.xmatters_api_enabled
    off = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path))
    assert not off.xmatters_enabled and off.xmatters_base_url == ""
    bogus = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL="acme.xmatters.com/x")
    assert not bogus.xmatters_enabled


def test_not_configured_receipts(stage1_pkg, tmp_path: Path) -> None:  # noqa: F811
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path))
    r = xm.send_stage(stage1_pkg, "body", settings=s)
    assert r.channel == "xmatters" and r.ok is False and r.detail.startswith("not configured: set XMATTERS_TRIGGER_URL")
    r = xm.send_note("inc-x", "text", "closure", settings=s)
    assert r.ok is False and r.stage == "closure"


# ------------------------------------------------------------------------------------------------ lifecycle
def test_stage1_raises_event_then_stage2_annotates_and_close_terminates(monkeypatch, stage1_pkg, stage2_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)

    r1 = xm.send_stage(stage1_pkg, "stage one body", settings=xm_settings)
    assert r1.ok and r1.stage == "stage1" and r1.channel == "xmatters"
    assert r1.detail == "event requested (requestId req-1, priority HIGH)"
    assert r1.target == "https://acme.xmatters.com/..."  # never the apiKey
    assert "SECRET-KEY-123" not in (r1.detail + r1.target)
    payload = fake.events["evt-uuid-1"]["payload"]
    assert payload["priority"] == "HIGH"
    assert payload["recipients"] == [{"id": "Platform On-call"}, {"id": "dominic.ops"}]  # id, not targetName: see _recipients
    props = payload["properties"]
    assert props["incident_id"] == stage1_pkg.incident_id and props["stage"] == "stage1" and props["severity"] == "critical"
    assert props["summary"].startswith("[CRITICAL] orders-api on ") and props["details"].endswith("stage one body")
    assert fake.calls[0]["init"]["auth"] == ("opsagent-key-id", "not-a-real-secret")
    state = json.loads((Path(xm_settings.outbox_path) / stage1_pkg.incident_id / "xmatters.json").read_text(encoding="utf-8"))
    assert state["request_id"] == "req-1" and state["event_id"] is None

    r2 = xm.send_stage(stage2_pkg, "ORDER_CACHE grows without bound", settings=xm_settings)
    assert r2.ok and r2.stage == "stage2"
    assert r2.detail == "annotated event 5001: diagnosis added"
    assert r2.target == "https://acme.xmatters.com/api/xm/1/events/evt-uuid-1"
    notes = fake.events["evt-uuid-1"]["annotations"]
    assert len(notes) == 1 and notes[0].startswith("Stage 2 of 2") and len(notes[0]) <= 1000
    # the annotation is a digest built from the package, not the card: root cause, code verdict and fixes
    assert stage2_pkg.diagnosis.root_cause.summary[:60] in notes[0]
    assert "Code verdict: shared" in notes[0] and "Immediate fix:" in notes[0]
    assert len(fake.events) == 1, "stage 2 must not raise a second event when it can annotate"
    state = xm.load_state(stage1_pkg.incident_id, xm_settings)
    assert state["event_id"] == "evt-uuid-1" and state["event_number"] == "5001"

    late = xm.send_note(stage1_pkg.incident_id, "still running", "delay", settings=xm_settings)
    assert late.ok and late.detail == "annotated event 5001: delay note added"

    done = xm.send_note(stage1_pkg.incident_id, "closed: root cause ...", "closure", settings=xm_settings, terminate=True)
    assert done.ok and done.detail == "annotated and terminated event 5001"
    assert fake.events["evt-uuid-1"]["status"] == "TERMINATED"
    assert fake.events["evt-uuid-1"]["annotations"][-1] == "closed: root cause ..."
    methods = [c.get("method") for c in fake.calls if "method" in c]
    assert methods == ["POST", "GET", "POST", "POST", "POST", "POST"]  # trigger; lookup+annotate; annotate; annotate+terminate


def test_without_api_credentials_later_stages_raise_follow_up_events(monkeypatch, stage1_pkg, stage2_pkg, trigger_only_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    s = trigger_only_settings

    assert xm.send_stage(stage1_pkg, "one", settings=s).ok
    assert fake.calls[0]["init"]["auth"] is None

    r2 = xm.send_stage(stage2_pkg, "two", settings=s)
    assert r2.ok and r2.detail.startswith("follow-up event requested (requestId req-2")
    assert len(fake.events) == 2 and fake.events["evt-uuid-2"]["payload"]["properties"]["stage"] == "stage2"
    assert "Stage 2 of 2" in fake.events["evt-uuid-2"]["payload"]["properties"]["details"]
    assert not any(c.get("method") == "GET" for c in fake.calls), "no xM API calls without credentials"

    late = xm.send_note(stage1_pkg.incident_id, "late", "delay", severity="critical", settings=s)
    assert late.ok and late.detail.startswith("follow-up event requested") and len(fake.events) == 3

    done = xm.send_note(stage1_pkg.incident_id, "closed", "closure", settings=s, terminate=True)
    assert done.ok is False and "credentials are not set" in done.detail
    assert len(fake.events) == 3, "a closure never pages anyone"
    state = xm.load_state(stage1_pkg.incident_id, s)
    assert state["request_id"] == "req-1" and [r["stage"] for r in state["requests"]] == ["stage1", "stage2", "delay"]


def test_event_not_yet_visible_falls_back_then_recovers(monkeypatch, stage1_pkg, stage2_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters(visible_after=1)  # the first lookup finds nothing (xMatters processes triggers asynchronously)
    _install(monkeypatch, fake)
    assert xm.send_stage(stage1_pkg, "one", settings=xm_settings).ok
    r2 = xm.send_stage(stage2_pkg, "two", settings=xm_settings)
    assert r2.ok and r2.detail.startswith("follow-up event requested")
    done = xm.send_note(stage1_pkg.incident_id, "closed", "closure", settings=xm_settings, terminate=True)
    assert done.ok and done.detail == "annotated and terminated event 5001"


def test_annotations_never_exceed_the_xmatters_limit(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    assert xm.send_stage(stage1_pkg, "one", settings=xm_settings).ok
    long_text = "\n".join(f"line {i}: " + "x" * 60 for i in range(80))  # ~5 KB closure text
    done = xm.send_note(stage1_pkg.incident_id, long_text, "closure", settings=xm_settings, terminate=True)
    assert done.ok, done.detail
    comment = fake.events["evt-uuid-1"]["annotations"][-1]
    assert len(comment) <= 1000 and comment.endswith("...") and comment.startswith("line 0:")
    assert xm.clamp("short") == "short"


def test_note_without_a_stage1_event(xm_settings) -> None:
    r = xm.send_note("inc-never-raised", "text", "closure", settings=xm_settings)
    assert r.ok is False and "no xMatters event was raised" in r.detail


def test_http_failures_become_receipts(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    _install(monkeypatch, FakeXMatters(fail_status=401))
    r = xm.send_stage(stage1_pkg, "body", settings=xm_settings)
    assert r.ok is False and "HTTP 401" in r.detail and "SECRET-KEY-123" not in r.detail

    class _Boom:
        def __init__(self, *a, **k):
            raise httpx.ConnectError("no route to xmatters")

    monkeypatch.setattr(xm.httpx, "Client", _Boom)
    r = xm.send_stage(stage1_pkg, "body", settings=xm_settings)
    assert r.ok is False and "ConnectError" in r.detail

    class _NoRequestId(FakeXMatters().client_factory()):
        def post(self, url, json=None, params=None, **k):
            return _Resp(200, {"status": "accepted"})

    monkeypatch.setattr(xm.httpx, "Client", _NoRequestId)
    r = xm.send_stage(stage1_pkg, "body", settings=xm_settings)
    assert r.ok is False and "no requestId" in r.detail


# ------------------------------------------------------------------------------------------------ policy + fan-out
def test_priority_comes_from_the_severity_policy(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    from opsagent.parsing import severity_policy as sp

    fake = FakeXMatters()
    _install(monkeypatch, fake)
    custom = sp.SeverityPolicy.model_validate({"rules": [{"severity": "critical", "when": "oom_event"}],
                                               "xmatters": {"critical": "MEDIUM"}})
    assert custom.event_priority("critical") == "MEDIUM" and custom.event_priority("warning") == "MEDIUM" and custom.event_priority("info") == "LOW"
    monkeypatch.setattr(sp, "get_policy", lambda: custom)
    r = xm.send_stage(stage1_pkg, "body", settings=xm_settings)
    assert r.ok and "priority MEDIUM" in r.detail and fake.events["evt-uuid-1"]["payload"]["priority"] == "MEDIUM"

    with pytest.raises(Exception):
        sp.SeverityPolicy.model_validate({"rules": [{"severity": "critical", "when": "oom_event"}], "xmatters": {"critical": "URGENT"}})


def test_deliver_fan_out_includes_xmatters(monkeypatch, stage1_pkg, stage2_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    r1 = {r.channel: r for r in deliver(stage1_pkg, settings=xm_settings)}
    assert set(r1) == {"outbox", "teams", "email", "servicenow", "xmatters"}
    assert r1["xmatters"].ok and r1["xmatters"].detail.startswith("event requested")
    assert "orders-api" in fake.events["evt-uuid-1"]["payload"]["properties"]["details"]  # the stage 1 card as text

    r2 = {r.channel: r for r in deliver(stage2_pkg, settings=xm_settings)}
    assert r2["xmatters"].ok and r2["xmatters"].detail.startswith("annotated event")

    late = {r.channel: r for r in deliver_delay_notice(stage1_pkg.incident_id, "orders-api", "critical", 310.0, settings=xm_settings)}
    assert late["xmatters"].ok and late["xmatters"].stage == "delay"

    closure = {r.channel: r for r in deliver_closure(stage1_pkg.incident_id, _kb(stage1_pkg), settings=xm_settings)}
    assert set(closure) == {"servicenow", "xmatters"}
    assert closure["xmatters"].ok and closure["xmatters"].detail == "annotated and terminated event 5001"
    assert closure["servicenow"].ok is False  # not configured in this fixture
    assert fake.events["evt-uuid-1"]["status"] == "TERMINATED"
    assert "unbounded in-process order cache" in fake.events["evt-uuid-1"]["annotations"][-1]


def test_property_map_for_the_stock_send_alert_form(monkeypatch, stage1_pkg, stage2_pkg, tmp_path: Path) -> None:  # noqa: F811
    form_trigger = "https://acme.xmatters.com/api/xm/1/forms/133b771f-03a6-4df0-b57c-f491364268ba/triggers"
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL=form_trigger,
                 XMATTERS_USER="u", XMATTERS_PASSWORD="p", XMATTERS_RECIPIENTS="L1 Support",
                 XMATTERS_PROPERTIES="summary=Summary, details=Message")
    assert s.xmatters_property_map == {"summary": "Summary", "details": "Message"}
    fake = FakeXMatters()
    _install(monkeypatch, fake)

    r1 = xm.send_stage(stage1_pkg, "stage one card", settings=s)
    assert r1.ok, r1.detail
    payload = fake.events["evt-uuid-1"]["payload"]
    assert set(payload["properties"]) == {"Summary", "Message"}  # nothing the form does not define
    assert payload["properties"]["Summary"].startswith("[CRITICAL] orders-api on ")
    assert payload["properties"]["Message"].startswith(f"OpsAgent incident {stage1_pkg.incident_id} (stage1)")
    assert "stage one card" in payload["properties"]["Message"]
    assert payload["recipients"] == [{"id": "L1 Support"}]
    assert fake.calls[1]["url"] == form_trigger

    # a follow-up event (no event visible yet) is mapped the same way
    fake.visible = False
    r2 = xm.send_stage(stage2_pkg, "diagnosis", settings=s)
    assert r2.ok and r2.detail.startswith("follow-up event requested")
    assert set(fake.events["evt-uuid-2"]["payload"]["properties"]) == {"Summary", "Message"}

    # a map that names none of the payload keys is a configuration error, reported, never a half-empty page
    broken = s.model_copy(update={"xmatters_properties": "subject=Summary"})
    r = xm.send_stage(stage1_pkg, "body", settings=broken)
    assert r.ok is False and "maps none of the payload keys" in r.detail


def test_closure_keeps_the_event_open_when_asked(monkeypatch, stage1_pkg, tmp_path: Path) -> None:  # noqa: F811
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL=TRIGGER,
                 XMATTERS_USER="u", XMATTERS_PASSWORD="p", XMATTERS_TERMINATE_ON_CLOSE="0")
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    assert xm.send_stage(stage1_pkg, "one", settings=s).ok
    closure = {r.channel: r for r in deliver_closure(stage1_pkg.incident_id, _kb(stage1_pkg), settings=s)}
    assert closure["xmatters"].ok and closure["xmatters"].detail == "annotated event 5001: closure note added"
    assert fake.events["evt-uuid-1"]["status"] == "ACTIVE"
