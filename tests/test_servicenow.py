"""Offline tests for the ServiceNow channel: a fake Table API records every request; no network."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from opsagent.config import Settings
from opsagent.notify import deliver, deliver_closure, deliver_delay_notice
from opsagent.notify import servicenow as sn
from opsagent.schemas.kb import KBRecord
from tests.test_notify import stage1_pkg, stage2_pkg  # noqa: F401 - fixtures


class _Resp:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeServiceNow:
    """Keeps incident records in memory and logs every call. Records are found by correlation_id like the real API."""

    def __init__(self, fail_status: int | None = None):
        self.records: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.fail_status = fail_status
        self._n = 10000

    def client_factory(self):
        fake = self

        class _Client:
            def __init__(self, *a, **k):
                fake.calls.append({"init": k})

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def get(self, url, params=None, **k):
                fake.calls.append({"method": "GET", "url": url, "params": params})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                q = (params or {}).get("sysparm_query", "")
                corr = q.split("correlation_id=")[1].split("^")[0] if "correlation_id=" in q else None
                hits = [r for r in fake.records.values() if r.get("correlation_id") == corr]
                return _Resp(200, {"result": [{k: v for k, v in h.items() if k in ("sys_id", "number", "state", "priority")} for h in hits[:1]]})

            def post(self, url, json=None, params=None, **k):
                fake.calls.append({"method": "POST", "url": url, "json": json})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                fake._n += 1
                rec = dict(json) | {"sys_id": f"sys{fake._n}", "number": f"INC{fake._n}", "priority": "1" if json.get("impact") == "1" else "3"}
                fake.records[rec["sys_id"]] = rec
                return _Resp(201, {"result": {"sys_id": rec["sys_id"], "number": rec["number"], "priority": rec["priority"]}})

            def patch(self, url, json=None, params=None, **k):
                fake.calls.append({"method": "PATCH", "url": url, "json": json})
                if fake.fail_status:
                    return _Resp(fake.fail_status, text="boom")
                sys_id = url.rsplit("/", 1)[1]
                rec = fake.records[sys_id]
                rec.setdefault("work_notes_log", []).append(json.get("work_notes", ""))
                rec.update({k: v for k, v in json.items() if k != "work_notes"})
                return _Resp(200, {"result": {"sys_id": sys_id, "number": rec["number"], "priority": rec["priority"]}})

        return _Client


@pytest.fixture()
def sn_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        SERVICENOW_INSTANCE="dev12345",
        SERVICENOW_USER="opsagent.integration",
        SERVICENOW_PASSWORD="not-a-real-password",
        SERVICENOW_ASSIGNMENT_GROUP="Platform On-call",
    )


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeServiceNow) -> None:
    monkeypatch.setattr(sn.httpx, "Client", fake.client_factory())


def test_base_url_forms() -> None:
    assert Settings(_env_file=None, SERVICENOW_INSTANCE="dev12345").servicenow_base_url == "https://dev12345.service-now.com"
    assert Settings(_env_file=None, SERVICENOW_INSTANCE="acme.service-now.com").servicenow_base_url == "https://acme.service-now.com"
    assert Settings(_env_file=None, SERVICENOW_INSTANCE="https://acme.service-now.com/").servicenow_base_url == "https://acme.service-now.com"
    assert Settings(_env_file=None, SERVICENOW_INSTANCE="dev12345").servicenow_enabled is False  # no credentials
    assert Settings(_env_file=None, SERVICENOW_INSTANCE="dev12345", SERVICENOW_TOKEN="t").servicenow_enabled is True


def test_not_configured_receipt(stage1_pkg, tmp_path: Path) -> None:  # noqa: F811
    s = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path))
    r = sn.send_stage(stage1_pkg, "body", settings=s)
    assert r.channel == "servicenow" and r.ok is False and r.detail.startswith("not configured")


def test_stage1_creates_then_stage2_adds_work_note(monkeypatch, stage1_pkg, stage2_pkg, sn_settings) -> None:  # noqa: F811
    fake = FakeServiceNow()
    _install(monkeypatch, fake)

    r1 = sn.send_stage(stage1_pkg, "stage one body", settings=sn_settings)
    assert r1.ok and r1.stage == "stage1"
    assert r1.detail.startswith("created INC10001 (priority 1)")
    assert r1.target == "https://dev12345.service-now.com/nav_to.do?uri=incident.do?sys_id=sys10001"
    created = fake.records["sys10001"]
    assert created["correlation_id"] == stage1_pkg.incident_id
    assert created["correlation_display"] == "OpsAgent"
    assert created["impact"] == "1" and created["urgency"] == "1"
    assert created["assignment_group"] == "Platform On-call"
    assert created["short_description"].startswith("[CRITICAL] orders-api on ")
    assert created["description"] == "stage one body"
    # credentials travel as basic auth, never inside the record or the receipt
    assert fake.calls[0]["init"]["auth"] == ("opsagent.integration", "not-a-real-password")
    assert "not-a-real-password" not in json.dumps(created) and "not-a-real-password" not in (r1.detail + (r1.target or ""))

    r2 = sn.send_stage(stage2_pkg, "ORDER_CACHE grows without bound", settings=sn_settings)
    assert r2.ok and r2.stage == "stage2"
    assert r2.detail.startswith("updated INC10001") and r2.detail.endswith("work note added")
    assert len(fake.records) == 1, "stage 2 must not open a second ticket"
    notes = fake.records["sys10001"]["work_notes_log"]
    assert len(notes) == 1 and "Stage 2 of 2" in notes[0] and "ORDER_CACHE" in notes[0]
    methods = [c.get("method") for c in fake.calls if "method" in c]
    assert methods == ["GET", "POST", "GET", "PATCH"]


def test_stage2_without_stage1_creates_and_annotates(monkeypatch, stage2_pkg, sn_settings) -> None:  # noqa: F811
    fake = FakeServiceNow()
    _install(monkeypatch, fake)
    r = sn.send_stage(stage2_pkg, "diag body", settings=sn_settings)
    assert r.ok and "stage 1 record was missing" in r.detail
    assert len(fake.records) == 1 and fake.records["sys10001"]["work_notes_log"]


def test_work_note_and_resolve(monkeypatch, stage1_pkg, sn_settings) -> None:  # noqa: F811
    fake = FakeServiceNow()
    _install(monkeypatch, fake)
    missing = sn.send_work_note("inc-none", "late", "delay", settings=sn_settings)
    assert missing.ok is False and "no ServiceNow record" in missing.detail

    sn.send_stage(stage1_pkg, "body", settings=sn_settings)
    late = sn.send_work_note(stage1_pkg.incident_id, "diagnosis still running", "delay", settings=sn_settings)
    assert late.ok and late.stage == "delay" and late.detail.startswith("updated INC10001")

    done = sn.send_work_note(stage1_pkg.incident_id, "closed", "closure", settings=sn_settings, resolve=True)
    assert done.ok and done.detail.startswith("resolved INC10001")
    rec = fake.records["sys10001"]
    assert rec["state"] == "6" and rec["close_code"] and rec["close_notes"] == "closed"


def test_http_failure_and_exception_become_receipts(monkeypatch, stage1_pkg, sn_settings) -> None:  # noqa: F811
    _install(monkeypatch, FakeServiceNow(fail_status=401))
    r = sn.send_stage(stage1_pkg, "body", settings=sn_settings)
    assert r.ok is False and "HTTP 401" in r.detail

    class _Boom:
        def __init__(self, *a, **k):
            raise httpx.ConnectError("no route to instance")

    monkeypatch.setattr(sn.httpx, "Client", _Boom)
    r = sn.send_stage(stage1_pkg, "body", settings=sn_settings)
    assert r.ok is False and "ConnectError" in r.detail


def test_deliver_fan_out_includes_servicenow(monkeypatch, stage1_pkg, stage2_pkg, sn_settings) -> None:  # noqa: F811
    fake = FakeServiceNow()
    _install(monkeypatch, fake)
    r1 = {r.channel: r for r in deliver(stage1_pkg, settings=sn_settings)}
    assert set(r1) == {"outbox", "teams", "email", "servicenow", "xmatters"}
    assert r1["servicenow"].ok and r1["servicenow"].detail.startswith("created")
    # the description is the stage 1 card rendered as text, so the ticket reads like the Teams card
    assert "orders-api" in fake.records["sys10001"]["description"]

    r2 = {r.channel: r for r in deliver(stage2_pkg, settings=sn_settings)}
    assert set(r2) == {"outbox", "teams", "email", "servicenow"}  # the heads-up call is stage 1 only
    assert r2["servicenow"].ok and r2["servicenow"].detail.startswith("updated")
    assert "ORDER_CACHE" in fake.records["sys10001"]["work_notes_log"][-1]

    late = {r.channel: r for r in deliver_delay_notice(stage1_pkg.incident_id, "orders-api", "critical", 310.0, settings=sn_settings)}
    assert late["servicenow"].ok and late["servicenow"].stage == "delay"

    kb = KBRecord(
        incident_id=stage1_pkg.incident_id, event_id=stage1_pkg.event_id, event_type="ec2.oom_kill", severity="critical",
        digest="orders-api OOM-killed", root_cause_summary="unbounded in-process order cache", root_cause_category="application_memory_leak",
        verdict="shared", code_location="app/orders/cache.py::ORDER_CACHE", immediate_fix="MemoryHigh=1228M MemoryMax=1536M",
        durable_fix="bound the cache", citations=["kb://systemd/resource-control#memorymax"], created_at=datetime.now(timezone.utc),
    )
    closure = deliver_closure(stage1_pkg.incident_id, kb, settings=sn_settings)
    assert [c.channel for c in closure] == ["servicenow", "xmatters"]
    assert closure[0].ok and closure[0].stage == "closure" and closure[1].ok is False  # xMatters not configured here
    last_note = fake.records["sys10001"]["work_notes_log"][-1]
    assert "unbounded in-process order cache" in last_note and "label" in last_note
    assert fake.records["sys10001"].get("state") != "6"  # resolve only when SERVICENOW_RESOLVE_ON_CLOSE=1


def test_closure_not_configured(tmp_path: Path) -> None:
    kb = KBRecord(incident_id="inc-x", event_id="e", event_type="t", severity="critical", digest="d",
                  root_cause_summary="r", created_at=datetime.now(timezone.utc))
    out = deliver_closure("inc-x", kb, settings=Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path)))
    assert [o.channel for o in out] == ["servicenow", "xmatters"]
    assert all(o.ok is False and o.stage == "closure" for o in out)


def test_short_description_does_not_repeat_the_service_prefix(stage1_pkg, sn_settings) -> None:  # noqa: F811
    # the flow's deterministic headline already starts with "<service> on <instance>: ..."
    pkg = stage1_pkg.model_copy(update={"headline": f"{stage1_pkg.service} on {stage1_pkg.instance_id}: process oom kill"})
    title = sn.incident_fields(pkg, "body", sn_settings)["short_description"]
    assert title == f"[CRITICAL] {stage1_pkg.service} on {stage1_pkg.instance_id}: process oom kill"
    assert title.count(stage1_pkg.service) == 1

    # a free-form headline (even one that names the service) still gets the service and instance in front
    pkg = stage1_pkg.model_copy(update={"headline": "orders-api OOM-killed by unbounded order cache"})
    title = sn.incident_fields(pkg, "body", sn_settings)["short_description"]
    assert title == f"[CRITICAL] {stage1_pkg.service} on {stage1_pkg.instance_id}: orders-api OOM-killed by unbounded order cache"


def test_timed_out_create_is_recovered_by_correlation_lookup(monkeypatch, stage1_pkg, sn_settings) -> None:  # noqa: F811
    """A hibernating developer instance may commit the record and still let the POST time out; the sender must
    find the record by correlation id instead of reporting a lost create (and must not open a duplicate)."""
    fake = FakeServiceNow()
    base_factory = fake.client_factory()

    class _SlowPost(base_factory):
        def post(self, url, json=None, params=None, **k):
            super().post(url, json=json, params=params, **k)  # the record lands server-side...
            raise httpx.ReadTimeout("The read operation timed out")  # ...but the response never arrives

    monkeypatch.setattr(sn.httpx, "Client", _SlowPost)
    r = sn.send_stage(stage1_pkg, "body", settings=sn_settings)
    assert r.ok, r.detail
    assert r.detail.startswith("created INC10001")
    assert len(fake.records) == 1
    methods = [c.get("method") for c in fake.calls if "method" in c]
    assert methods == ["GET", "POST", "GET"]

    # when the record truly never landed, the timeout is still reported as a failed delivery
    empty = FakeServiceNow()

    class _LostPost(empty.client_factory()):
        def post(self, url, json=None, params=None, **k):
            raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(sn.httpx, "Client", _LostPost)
    r = sn.send_stage(stage1_pkg, "body", settings=sn_settings)
    assert r.ok is False and "ReadTimeout" in r.detail and not empty.records


def test_client_timeout_allows_for_instance_wake_up(sn_settings) -> None:
    assert sn.ServiceNowClient(sn_settings).timeout >= 30
