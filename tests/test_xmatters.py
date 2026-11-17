"""Offline tests for the xMatters heads-up call: a fake trigger URL + xM API records every request; no network."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from opsagent.config import Settings
from opsagent.notify import deliver, deliver_closure, deliver_delay_notice
from opsagent.notify import xmatters as xm
from opsagent.schemas.kb import KBRecord
from tests.test_notify import stage1_pkg, stage2_pkg  # noqa: F401 - fixtures

FORM_TRIGGER = "https://acme.xmatters.com/api/xm/1/forms/133b771f-03a6-4df0-b57c-f491364268ba/triggers"
FLOW_TRIGGER = "https://acme.xmatters.com/api/integration/1/functions/0a1b2c3d/triggers?apiKey=SECRET-KEY-123"


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
    """A form trigger answers with the event (id, eventId, requestId); `flow_designer=True` answers with the requestId
    only, and the event becomes visible to GET /events?requestId after `visible_after` polls."""

    def __init__(self, fail_status: int | None = None, flow_designer: bool = False, visible_after: int = 0):
        self.calls: list[dict] = []
        self.events: dict[str, dict] = {}  # event uuid -> record
        self.by_request: dict[str, str] = {}
        self.fail_status = fail_status
        self.flow_designer = flow_designer
        self.visible_after = visible_after
        self._n = 0
        self._polls = 0

    @property
    def posts(self) -> list[dict]:
        return [c for c in self.calls if c.get("method") == "POST"]

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
                    fake.events[uuid] = {"id": uuid, "eventId": str(94000000 + fake._n), "status": "ACTIVE", "payload": json}
                    fake.by_request[rid] = uuid
                    if fake.flow_designer:
                        return _Resp(202, {"requestId": rid})
                    return _Resp(200, {"id": uuid, "eventId": fake.events[uuid]["eventId"], "requestId": rid, "status": "ACTIVE"})
                if url.endswith("/api/xm/1/events"):
                    fake.events[json["id"]]["status"] = json["status"]
                    return _Resp(202, {"id": json["id"], "status": json["status"]})
                return _Resp(404, text="unknown endpoint")

            def get(self, url, params=None, **k):
                fake.calls.append({"method": "GET", "url": url, "params": params})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                fake._polls += 1
                uuid = fake.by_request.get((params or {}).get("requestId", ""))
                if not uuid or fake._polls <= fake.visible_after:
                    return _Resp(200, {"count": 0, "total": 0, "data": []})
                e = fake.events[uuid]
                return _Resp(200, {"count": 1, "total": 1, "data": [{"id": e["id"], "eventId": e["eventId"], "status": e["status"]}]})

        return _Client


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeXMatters) -> None:
    monkeypatch.setattr(xm.httpx, "Client", fake.client_factory())


def _kb(pkg) -> KBRecord:
    return KBRecord(
        incident_id=pkg.incident_id, event_id=pkg.event_id, event_type="ec2.oom_kill", severity="critical",
        digest="orders-api OOM-killed", root_cause_summary="unbounded in-process order cache", root_cause_category="application_memory_leak",
        verdict="shared", code_location="app/orders/cache.py::ORDER_CACHE", immediate_fix="MemoryHigh=1228M MemoryMax=1536M",
        durable_fix="bound the cache", citations=["kb://systemd/resource-control#memorymax"], created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def xm_settings(tmp_path: Path) -> Settings:
    """The live shape: Send Alert form trigger, phones only."""
    return Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        XMATTERS_TRIGGER_URL=FORM_TRIGGER,
        XMATTERS_USER="oncall@acme.example",
        XMATTERS_PASSWORD="not-a-real-secret",
        XMATTERS_RECIPIENTS="L1 Support",
        XMATTERS_DEVICES="Mobile Phone, Work Phone",
        XMATTERS_PROPERTIES="summary=Summary,details=Message",
    )


@pytest.fixture()
def custom_form_settings(tmp_path: Path) -> Settings:
    """A Flow Designer trigger whose form defines OpsAgent's own property names; no device filter."""
    return Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        XMATTERS_TRIGGER_URL=FLOW_TRIGGER,
        XMATTERS_USER="opsagent-key-id",
        XMATTERS_PASSWORD="not-a-real-secret",
        XMATTERS_RECIPIENTS="Platform On-call, dominic.ops",
    )


# ------------------------------------------------------------------------------------------------ the call
def test_headsup_rings_phones_with_a_spoken_message(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    r = xm.send_headsup(stage1_pkg, settings=xm_settings, ticket="INC0010004")
    assert r.ok, r.detail
    assert r.channel == "xmatters" and r.stage == "stage1"
    assert r.detail == "heads-up event 94000001 raised (priority HIGH) for L1 Support on Mobile Phone, Work Phone"
    assert r.target == "https://acme.xmatters.com/api/xm/1/events/evt-uuid-1"

    assert fake.posts[0]["url"] == FORM_TRIGGER
    payload = fake.posts[0]["json"]
    assert payload["priority"] == "HIGH"  # critical -> HIGH from the severity policy
    assert payload["recipients"] == [{"id": "L1 Support"}]  # id, not targetName: the form trigger drops targetName
    assert payload["targetDeviceNames"] == ["Mobile Phone", "Work Phone"]
    assert payload["voicemailOptions"] == {"retry": 0, "every": 60, "leave": "messageonly"}
    assert set(payload["properties"]) == {"Summary", "Message"}  # nothing the Send Alert form does not define
    assert payload["properties"]["Summary"] == f"{stage1_pkg.brand} OpsAgent heads-up: critical incident on orders-api"
    spoken = payload["properties"]["Message"]
    assert spoken.startswith(f"{stage1_pkg.brand} OpsAgent heads-up. A critical incident is open on orders-api. ")
    assert "ServiceNow ticket INC0010004 has the stage one report." in spoken
    assert spoken.endswith("The diagnosis follows there in a minute or two.")
    for forbidden in ("\n", "#", "*", "http", stage1_pkg.incident_id):
        assert forbidden not in spoken, forbidden

    state = xm.load_state(stage1_pkg.incident_id, xm_settings)
    assert state["event_id"] == "evt-uuid-1" and state["event_number"] == "94000001" and state["request_id"] == "req-1"
    assert state["devices"] == ["Mobile Phone", "Work Phone"] and state["ticket"] == "INC0010004"


def test_headsup_without_a_ticket_and_with_a_custom_form(monkeypatch, stage1_pkg, custom_form_settings) -> None:  # noqa: F811
    fake = FakeXMatters(flow_designer=True)
    _install(monkeypatch, fake)
    r = xm.send_headsup(stage1_pkg, settings=custom_form_settings)
    assert r.ok and r.detail == "heads-up event requestId req-1 raised (priority HIGH) for Platform On-call, dominic.ops on every device"
    assert r.target == "https://acme.xmatters.com/..."  # the apiKey in the trigger URL never reaches a receipt
    payload = fake.posts[0]["json"]
    assert "targetDeviceNames" not in payload
    props = payload["properties"]
    assert set(props) == {"incident_id", "event_id", "severity", "service", "instance_id", "ticket", "summary", "details", "brand", "trace_url"}
    assert props["ticket"] == "" and props["incident_id"] == stage1_pkg.incident_id
    assert "The stage one report is on its way." in props["details"] and "ServiceNow" not in props["details"]
    state = xm.load_state(stage1_pkg.incident_id, custom_form_settings)
    assert state["event_id"] is None and state["request_id"] == "req-1"


def test_headsup_is_placed_once_per_incident(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    assert xm.send_headsup(stage1_pkg, settings=xm_settings).ok
    again = xm.send_headsup(stage1_pkg, settings=xm_settings)
    assert again.ok and again.detail.startswith(f"heads-up already placed for {stage1_pkg.incident_id} (event 94000001)")
    assert len(fake.posts) == 1  # no second call to on-call


def test_spoken_message_ends_sentences_and_stays_plain(stage1_pkg) -> None:  # noqa: F811
    text = xm.spoken_message(stage1_pkg, ticket="INC0000001")
    sentences = [s for s in text.split(". ") if s]
    assert len(sentences) >= 4 and text.endswith(".")
    assert xm._sentence("already done.") == "Already done." and xm._sentence("  two   words ") == "Two words."
    assert xm._sentence("") == ""


def test_spoken_message_falls_back_to_the_summary_for_a_label_headline(stage1_pkg) -> None:  # noqa: F811
    # the live triage sometimes produces "orders-api on i-...: process oom kill"; say the analyst's first sentence instead
    label = stage1_pkg.model_copy(update={
        "headline": f"orders-api on {stage1_pkg.instance_id}: process oom kill",
        "summary": "The orders-api service experienced an out-of-memory condition where the kernel killed the python3 process "
                   "after rapid memory growth, and the service has restarted twice. Further analysis follows. " + "x" * 400,
    })
    assert label.short_headline == "process oom kill"
    text = xm.spoken_message(label)
    assert "process oom kill" not in text
    assert "The orders-api service experienced an out-of-memory condition" in text
    assert "restarted twice. The stage one report is on its way." in text
    assert "xxxx" not in text
    # a long first sentence is cut at a word boundary
    long_first = label.model_copy(update={"summary": "word " * 120 + ". tail"})
    what = xm._what_happened(long_first)
    assert len(what) <= xm.MAX_WHAT_CHARS + 1 and what.endswith("word.")
    # an informative headline is spoken as it is
    assert xm._what_happened(stage1_pkg) == xm._sentence(stage1_pkg.short_headline)


def test_property_map_matching_nothing_is_a_configuration_error(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    _install(monkeypatch, FakeXMatters())
    broken = xm_settings.model_copy(update={"xmatters_properties": "subject=Summary"})
    r = xm.send_headsup(stage1_pkg, settings=broken)
    assert r.ok is False and "maps none of the payload keys" in r.detail


def test_trigger_failures_are_receipts(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    _install(monkeypatch, FakeXMatters(fail_status=401))
    r = xm.send_headsup(stage1_pkg, settings=xm_settings)
    assert r.ok is False and r.detail.startswith("XMattersError: HTTP 401")
    assert xm.load_state(stage1_pkg.incident_id, xm_settings) == {}  # nothing to terminate later


# ------------------------------------------------------------------------------------------------ the close
def test_close_terminates_the_event(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    assert xm.send_headsup(stage1_pkg, settings=xm_settings).ok
    r = xm.close_event(stage1_pkg.incident_id, settings=xm_settings)
    assert r.ok and r.stage == "closure"
    assert r.detail == "terminated heads-up event 94000001: call retries and escalation stopped"
    assert fake.events["evt-uuid-1"]["status"] == "TERMINATED"
    assert fake.posts[-1]["json"] == {"id": "evt-uuid-1", "status": "TERMINATED"}
    assert xm.load_state(stage1_pkg.incident_id, xm_settings)["terminated_at"]


def test_close_resolves_a_flow_designer_event_by_request_id(monkeypatch, stage1_pkg, custom_form_settings) -> None:  # noqa: F811
    fake = FakeXMatters(flow_designer=True, visible_after=1)
    _install(monkeypatch, fake)
    assert xm.send_headsup(stage1_pkg, settings=custom_form_settings).ok
    early = xm.close_event(stage1_pkg.incident_id, settings=custom_form_settings)
    assert early.ok is False and "not visible yet (requestId req-1)" in early.detail
    late = xm.close_event(stage1_pkg.incident_id, settings=custom_form_settings)
    assert late.ok and "terminated heads-up event 94000001" in late.detail
    assert fake.events["evt-uuid-1"]["status"] == "TERMINATED"
    assert xm.load_state(stage1_pkg.incident_id, custom_form_settings)["event_id"] == "evt-uuid-1"


def test_close_without_credentials_or_without_a_call(monkeypatch, stage1_pkg, tmp_path: Path) -> None:  # noqa: F811
    fake = FakeXMatters(flow_designer=True)
    _install(monkeypatch, fake)
    trigger_only = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL=FLOW_TRIGGER)
    assert trigger_only.xmatters_enabled and not trigger_only.xmatters_api_enabled
    nothing = xm.close_event(stage1_pkg.incident_id, settings=trigger_only)
    assert nothing.ok is False and nothing.detail == f"no xMatters heads-up was placed for {stage1_pkg.incident_id}"
    assert xm.send_headsup(stage1_pkg, settings=trigger_only).ok  # a Flow Designer trigger pages without xM API credentials
    r = xm.close_event(stage1_pkg.incident_id, settings=trigger_only)
    assert r.ok is False and "XMATTERS_USER / XMATTERS_PASSWORD not set" in r.detail
    assert fake.events["evt-uuid-1"]["status"] == "ACTIVE"


def test_not_configured(stage1_pkg, tmp_path: Path) -> None:  # noqa: F811
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path))
    assert not s.xmatters_enabled
    assert xm.send_headsup(stage1_pkg, settings=s).detail == xm.NOT_CONFIGURED
    assert xm.close_event(stage1_pkg.incident_id, settings=s).detail == xm.NOT_CONFIGURED


# ------------------------------------------------------------------------------------------------ in the fan-out
def test_deliver_calls_at_stage1_only_and_hangs_up_on_close(monkeypatch, stage1_pkg, stage2_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)

    r1 = {r.channel: r for r in deliver(stage1_pkg, settings=xm_settings)}
    assert set(r1) == {"outbox", "teams", "email", "servicenow", "xmatters"}
    assert r1["xmatters"].ok and r1["xmatters"].detail.startswith("heads-up event 94000001 raised")
    spoken = fake.posts[0]["json"]["properties"]["Message"]
    assert "The stage one report is on its way." in spoken  # ServiceNow is not configured here, so no ticket number

    r2 = {r.channel: r for r in deliver(stage2_pkg, settings=xm_settings)}
    assert set(r2) == {"outbox", "teams", "email", "servicenow"}  # the diagnosis does not go to xMatters
    late = {r.channel for r in deliver_delay_notice(stage1_pkg.incident_id, "orders-api", "critical", 310.0, settings=xm_settings)}
    assert late == {"outbox", "teams", "email", "servicenow"}
    assert len(fake.posts) == 1  # still the single call

    closure = deliver_closure(stage1_pkg.incident_id, _kb(stage1_pkg), settings=xm_settings)
    assert [c.channel for c in closure] == ["servicenow", "xmatters"]
    assert closure[1].ok and closure[1].detail.startswith("terminated heads-up event 94000001")
    assert fake.events["evt-uuid-1"]["status"] == "TERMINATED"


def test_closure_keeps_the_event_open_when_asked(monkeypatch, stage1_pkg, xm_settings) -> None:  # noqa: F811
    fake = FakeXMatters()
    _install(monkeypatch, fake)
    keep = xm_settings.model_copy(update={"xmatters_terminate_on_close": False})
    assert deliver(stage1_pkg, settings=keep)[-1].ok
    closure = deliver_closure(stage1_pkg.incident_id, _kb(stage1_pkg), settings=keep)
    assert closure[1].ok and closure[1].detail.startswith("heads-up event left open (XMATTERS_TERMINATE_ON_CLOSE=0)")
    assert fake.events["evt-uuid-1"]["status"] == "ACTIVE"
    assert len(fake.posts) == 1


def test_settings_parse_devices_and_properties(tmp_path: Path) -> None:
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), XMATTERS_TRIGGER_URL=FORM_TRIGGER,
                 XMATTERS_DEVICES=" Mobile Phone ,Work Phone,, ", XMATTERS_PROPERTIES="summary=Summary, details=Message")
    assert s.xmatters_device_names == ["Mobile Phone", "Work Phone"]
    assert s.xmatters_property_map == {"summary": "Summary", "details": "Message"}
    assert s.xmatters_base_url == "https://acme.xmatters.com"
    assert Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path)).xmatters_device_names == []
