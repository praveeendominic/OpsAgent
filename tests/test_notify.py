"""Offline tests for opsagent.notify: cards, email rendering, Teams/SMTP delivery (monkeypatched) and the outbox."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from opsagent.config import Settings
from opsagent.notify import (
    build_delay_card,
    build_eml,
    build_stage1_card,
    build_stage2_card,
    card_to_html,
    card_to_markdown,
    deliver,
    deliver_delay_notice,
    render_email,
    send_card,
    send_email,
    wrap_for_teams,
    write_outbox,
)
from opsagent.notify import teams as teams_module
from opsagent.notify import email as email_module
from opsagent.schemas.code_correlation import CodeCorrelation, CodeLocation, RecentCommit
from opsagent.schemas.diagnosis import Citation, Diagnosis, Fix, RootCause, TimelineEntry
from opsagent.schemas.incident import IncidentPackage
from opsagent.schemas.raw import AlarmInfo, Window
from opsagent.schemas.triage import (
    Classification,
    Evidence,
    InstanceDetails,
    LeakProfile,
    OOMEvent,
    ServiceEvent,
    TopError,
    TriageRecord,
)

ALARM_AT = datetime(2026, 11, 14, 9, 40, 12, tzinfo=timezone.utc)
INCIDENT_ID = "INC-20261114-0001"
EVENT_ID = "evt-7f3a9c"
INSTANCE = "i-0ab12cd34ef56789a"
SERVICE = "orders-api"

DROP_IN = (
    "# /etc/systemd/system/orders-api.service.d/10-memory.conf\n"
    "[Service]\n"
    "MemoryHigh=1200M\n"
    "MemoryMax=1500M\n"
    "Restart=always\n"
    "RestartSec=5\n"
)


# --------------------------------------------------------------------------- fixtures
def _triage() -> TriageRecord:
    return TriageRecord(
        event_id=EVENT_ID,
        incident_id=INCIDENT_ID,
        event_type="memory",
        alarm=AlarmInfo(
            name="orders-api-mem-high",
            fired_at=ALARM_AT,
            reason="Threshold crossed: MemoryUtilization > 90 for 3 datapoints",
            metric="MemoryUtilization",
            threshold=90.0,
        ),
        instance=InstanceDetails(
            instance_id=INSTANCE,
            instance_type="t3.small",
            total_memory_mb=2048,
            vcpus=2,
            swap_mb=0,
            region="eu-west-1",
            tags={"app": SERVICE, "owner": "orders-team", "env": "prod"},
            source="inventory",
        ),
        window=Window(start=ALARM_AT - timedelta(minutes=10), end=ALARM_AT + timedelta(minutes=1)),
        service=SERVICE,
        owner="orders-team",
        evidence=Evidence(
            oom_events=[
                OOMEvent(
                    timestamp=ALARM_AT - timedelta(seconds=20),
                    killed_process="python3",
                    killed_pid=4525,
                    anon_rss_kb=1600620,
                    total_vm_kb=2211844,
                    file_rss_kb=0,
                    cgroup="/system.slice/orders-api.service",
                    uid=1001,
                    invoked_by="python3",
                )
            ],
            service_events=[
                ServiceEvent(
                    timestamp=ALARM_AT - timedelta(seconds=19),
                    unit="orders-api.service",
                    event="killed",
                    result="oom-kill",
                    signal="SIGKILL",
                    restart_counter=2,
                    memory_peak_mb=1563.1,
                ),
                ServiceEvent(
                    timestamp=ALARM_AT - timedelta(seconds=14),
                    unit="orders-api.service",
                    event="restart_scheduled",
                    restart_counter=2,
                ),
            ],
            leak_profile=LeakProfile(
                start=ALARM_AT - timedelta(minutes=6),
                end=ALARM_AT - timedelta(seconds=20),
                first_rss_mb=210.0,
                peak_rss_mb=1563.1,
                slope_mb_per_min=238.0,
                mem_available_pct_at_kill=3.2,
                samples=12,
                step_mb=120.0,
                interval_s=30.0,
            ),
            top_errors=[
                TopError(message="order cache size 1_842_311 entries; eviction disabled", count=37, level="WARNING"),
                TopError(message="MemoryError in OrderCache.put", count=3),
            ],
            restart_count=2,
            notes=["unit restarted twice within the window"],
        ),
        classification=Classification(
            reason="memory",
            sub_reason="application_leak",
            confidence="high",
            rule="oom_kill+linear_growth",
            rationale="OOM kill of the service process after monotonic RSS growth of 238 MB/min with no competing process.",
        ),
        severity="critical",
        summary=(
            "orders-api on i-0ab12cd34ef56789a was OOM-killed (pid 4525 at 1563 MB) after six minutes of steady "
            "memory growth at 238 MB/min. systemd restarted the unit twice; the leak pattern repeats after each restart."
        ),
        analyst_agrees=True,
        analyst_note="",
        created_at=ALARM_AT + timedelta(seconds=48),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        event_id=EVENT_ID,
        incident_id=INCIDENT_ID,
        timeline=[
            TimelineEntry(ts=(ALARM_AT - timedelta(minutes=6)).isoformat(), source="metric", what="RSS begins linear climb"),
            TimelineEntry(ts=(ALARM_AT - timedelta(seconds=20)).isoformat(), source="system log", what="oom-kill pid 4525"),
            TimelineEntry(ts=ALARM_AT.isoformat(), source="alarm", what="orders-api-mem-high fired"),
        ],
        root_cause=RootCause(
            summary=(
                "The orders-api process keeps every fetched order in an unbounded in-process cache. Under the "
                "evening order burst the cache grows about 238 MB per minute until the kernel OOM-kills the process; "
                "the restart clears memory so the pattern repeats."
            ),
            category="application_memory_leak",
            contributing=["t3.small with 2 GB RAM and no swap", "no MemoryMax on the unit"],
            confidence="high",
        ),
        citations=[
            Citation(title="Runbook: OOM kills on systemd services", source="kb://runbooks/oom-kill-systemd.md"),
            Citation(title="systemd.resource-control MemoryHigh/MemoryMax", source="https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html"),
            Citation(title="Postmortem: catalog-api cache growth", source="kb://postmortems/catalog-api-cache.md"),
        ],
        fixes=[
            Fix(
                horizon="immediate",
                owner="ops",
                action="set_unit_memory_limits",
                detail="Cap the unit so the kernel throttles and restarts orders-api before it starves the host.",
                command=DROP_IN,
                reversal="rm the drop-in and run systemctl daemon-reload && systemctl restart orders-api",
            ),
            Fix(
                horizon="durable",
                owner="dev",
                action="bound_cache",
                detail="Give ORDER_CACHE a maximum size with LRU eviction and a TTL, and expose its size as a metric.",
                command=None,
            ),
        ],
        classification_agreement="agreed",
        notes="",
        created_at=ALARM_AT + timedelta(seconds=170),
    )


def _code_correlation() -> CodeCorrelation:
    return CodeCorrelation(
        event_id=EVENT_ID,
        incident_id=INCIDENT_ID,
        repository="orders-api",
        verdict="shared",
        confidence=0.82,
        pattern="unbounded_growth",
        locations=[
            CodeLocation(
                file="app/orders/cache.py",
                symbol="ORDER_CACHE",
                line=14,
                excerpt="ORDER_CACHE: dict[str, Order] = {}\n\ndef put(order: Order) -> None:\n    ORDER_CACHE[order.id] = order",
                why="module-level dict with no eviction; every fetched order is retained for the life of the process",
            )
        ],
        explanation=(
            "ORDER_CACHE is a module-level dict that is only ever written to. The warning 'eviction disabled' in the "
            "app log matches the code path, and the growth rate matches the order rate."
        ),
        developer_action="Replace ORDER_CACHE with a bounded LRU (maxsize 50_000) plus a 15 minute TTL.",
        recent_commits=[
            RecentCommit(sha="9f1c2ab", date="2026-11-10", message="cache full orders for the recommendations widget", files=["app/orders/cache.py"]),
        ],
        created_at=ALARM_AT + timedelta(seconds=200),
    )


@pytest.fixture
def stage1_pkg() -> IncidentPackage:
    t = _triage()
    return IncidentPackage(
        incident_id=INCIDENT_ID,
        event_id=EVENT_ID,
        stage="stage1",
        severity="critical",
        service=SERVICE,
        instance_id=INSTANCE,
        headline="orders-api OOM-killed after a 238 MB/min memory leak",
        summary=t.summary or "",
        triage=t,
        timings={"stage1": 58.0},
        created_at=ALARM_AT + timedelta(seconds=58),
    )


@pytest.fixture
def stage2_pkg(stage1_pkg: IncidentPackage) -> IncidentPackage:
    diag = _diagnosis()
    return stage1_pkg.model_copy(
        update={
            "stage": "stage2",
            "summary": (
                "Root cause: an unbounded in-process order cache in orders-api. Verdict shared: the code leaks and the "
                "unit has no memory limit. Apply the MemoryHigh/MemoryMax drop-in now; bound the cache this week."
            ),
            "diagnosis": diag,
            "code_correlation": _code_correlation(),
            "recommended_fix": diag.immediate_fix,
            "durable_fix": diag.durable_fix,
            "timings": {"stage1": 58.0, "stage2": 214.0},
            "trace_url": "https://langfuse.example.invalid/trace/abc123",
            "created_at": ALARM_AT + timedelta(seconds=214),
        }
    )


@pytest.fixture
def unconfigured(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), TEAMS_WEBHOOK_URL="", SMTP_HOST="", SMTP_FROM="", SMTP_TO="")


# --------------------------------------------------------------------------- helpers
def _assert_card_shape(card: dict) -> None:
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.5"
    assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
    assert isinstance(card["body"], list) and card["body"]
    assert isinstance(card["actions"], list)
    for el in card["body"]:
        assert "type" in el
        if el["type"] == "FactSet":
            assert el["facts"], "empty FactSet"
            for fact in el["facts"]:
                assert isinstance(fact["title"], str) and fact["title"]
                assert isinstance(fact["value"], str) and fact["value"]
        if el["type"] == "TextBlock":
            assert isinstance(el["text"], str)
    json.dumps(card)  # must be serialisable


# --------------------------------------------------------------------------- cards
def test_stage1_card_structure(stage1_pkg: IncidentPackage) -> None:
    card = build_stage1_card(stage1_pkg)
    _assert_card_shape(card)
    header = card["body"][1]
    assert header["color"] == "attention"
    assert "CRITICAL" in header["text"] and SERVICE in header["text"]
    facts = {f["title"]: f["value"] for el in card["body"] if el["type"] == "FactSet" for f in el["facts"]}
    assert facts["Incident"] == INCIDENT_ID
    assert facts["Instance"] == INSTANCE
    assert facts["Alarm"] == "orders-api-mem-high"
    assert facts["Leak slope"].startswith("238 MB/min")
    assert facts["Restart counter"] == "2"
    assert "4525" in facts["OOM kill"] and "1600620 kB" in facts["OOM kill"]
    assert facts["Time since alarm"] == "58 s"
    assert not any(el.get("type") == "Action.Submit" for el in card["actions"])
    assert "ORDER_CACHE" not in json.dumps(card)


def test_warning_severity_colour(stage1_pkg: IncidentPackage) -> None:
    pkg = stage1_pkg.model_copy(update={"severity": "warning"})
    card = build_stage1_card(pkg)
    assert card["body"][1]["color"] == "warning"


def test_stage2_card_structure(stage2_pkg: IncidentPackage) -> None:
    card = build_stage2_card(stage2_pkg)
    _assert_card_shape(card)
    blob = json.dumps(card)
    assert "ORDER_CACHE" in blob
    assert "MemoryHigh" in blob
    headings = [el["text"] for el in card["body"] if el.get("separator") and el.get("weight") == "Bolder"]
    assert headings == ["Root cause", "Citations", "Code verdict", "Recommended immediate fix", "Durable fix"]
    mono = [el for el in card["body"] if el.get("fontType") == "Monospace"]
    assert mono and "MemoryMax=1500M" in mono[0]["text"]
    citation_sets = [
        el for el in card["body"] if el["type"] == "FactSet" and any(f["value"].startswith("kb://") for f in el["facts"])
    ]
    assert citation_sets and len(citation_sets[0]["facts"]) <= 5
    kinds = [a["type"] for a in card["actions"]]
    assert kinds == ["Action.OpenUrl", "Action.Submit", "Action.Submit"]
    assert card["actions"][0]["url"] == stage2_pkg.trace_url
    assert [a["title"] for a in card["actions"][1:]] == ["Accept RCA", "RCA is wrong"]
    for a in card["actions"][1:]:
        assert a["data"]["incident_id"] == INCIDENT_ID and a["data"]["label"]


def test_citations_capped_at_five(stage2_pkg: IncidentPackage) -> None:
    diag = stage2_pkg.diagnosis.model_copy(
        update={"citations": [Citation(title=f"Doc {i}", source=f"kb://doc-{i}.md") for i in range(8)]}
    )
    card = build_stage2_card(stage2_pkg.model_copy(update={"diagnosis": diag}))
    idx = next(i for i, el in enumerate(card["body"]) if el.get("text") == "Citations")
    assert len(card["body"][idx + 1]["facts"]) == 5


def test_delay_card_and_wrapper() -> None:
    card = build_delay_card(INCIDENT_ID, SERVICE, "critical", 305.0)
    _assert_card_shape(card)
    facts = {f["title"]: f["value"] for el in card["body"] if el["type"] == "FactSet" for f in el["facts"]}
    assert facts["Incident"] == INCIDENT_ID
    assert facts["Elapsed since alarm"] == "5 min 05 s"
    wrapped = wrap_for_teams(card)
    assert wrapped["type"] == "message"
    att = wrapped["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["contentUrl"] is None
    assert att["content"] is card


def test_card_renderings(stage2_pkg: IncidentPackage) -> None:
    card = build_stage2_card(stage2_pkg)
    md = card_to_markdown(card)
    assert INCIDENT_ID in md
    assert "## Root cause" in md
    assert "```" in md and "MemoryHigh=1200M" in md
    html = card_to_html(card)
    assert INCIDENT_ID in html
    assert "<pre" in html and "MemoryHigh=1200M" in html
    assert "<table" in html
    assert stage2_pkg.trace_url in html


# --------------------------------------------------------------------------- email
def test_render_email(stage1_pkg: IncidentPackage, stage2_pkg: IncidentPackage) -> None:
    subject, text, html = render_email(stage1_pkg)
    assert subject.startswith("[CRITICAL]")
    assert subject == f"[CRITICAL] {SERVICE} on {INSTANCE}: {stage1_pkg.headline} ({INCIDENT_ID}, stage 1)"
    assert INCIDENT_ID in text and "238 MB/min" in text
    assert "ROOT CAUSE" not in text
    assert "<html" in html and INCIDENT_ID in html

    subject2, text2, html2 = render_email(stage2_pkg)
    assert subject2.endswith("stage 2)")
    assert "ROOT CAUSE" in text2 and "ORDER_CACHE" in text2 and "MemoryHigh=1200M" in text2
    assert "Code verdict" in html2 and "ORDER_CACHE" in html2 and "MemoryMax=1500M" in html2

    eml = build_eml(subject2, text2, html2)
    assert isinstance(eml, bytes)
    assert b"Content-Type: multipart/alternative" in eml
    assert b"Subject:" in eml


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port = host, port
        self.calls: list[tuple] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc) -> None:
        self.calls.append(("quit",))

    def ehlo(self) -> None:
        self.calls.append(("ehlo",))

    def starttls(self) -> None:
        self.calls.append(("starttls",))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def send_message(self, msg, from_addr=None, to_addrs=None) -> None:
        self.calls.append(("send", msg["Subject"], from_addr, tuple(to_addrs)))


def test_send_email_records_login_and_send(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_module.smtplib, "SMTP", _FakeSMTP)
    settings = Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        SMTP_HOST="smtp.example.invalid",
        SMTP_PORT=587,
        SMTP_USER="relay-user",
        SMTP_PASSWORD="relay-pass",
        SMTP_FROM="opsagent@example.invalid",
        SMTP_TO="oncall@example.invalid, ops-leads@example.invalid",
    )
    receipt = send_email("[CRITICAL] test", "plain", "<p>html</p>", settings=settings)
    assert receipt.ok is True
    assert receipt.channel == "email"
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.invalid" and smtp.port == 587
    names = [c[0] for c in smtp.calls]
    assert "starttls" in names and "login" in names and "send" in names
    assert names.index("starttls") < names.index("login") < names.index("send")
    login = next(c for c in smtp.calls if c[0] == "login")
    assert login[1:] == ("relay-user", "relay-pass")
    sent = next(c for c in smtp.calls if c[0] == "send")
    assert sent[1] == "[CRITICAL] test"
    assert sent[2] == "opsagent@example.invalid"
    assert sent[3] == ("oncall@example.invalid", "ops-leads@example.invalid")


def test_send_email_failure_is_a_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Boom:
        def __init__(self, *a, **k) -> None:
            raise ConnectionRefusedError("relay down")

    monkeypatch.setattr(email_module.smtplib, "SMTP", _Boom)
    settings = Settings(
        _env_file=None,
        OPSAGENT_OUTBOX_DIR=str(tmp_path),
        SMTP_HOST="smtp.example.invalid",
        SMTP_FROM="opsagent@example.invalid",
        SMTP_TO="oncall@example.invalid",
    )
    receipt = send_email("s", "t", "<p>h</p>", settings=settings)
    assert receipt.ok is False
    assert "relay down" in receipt.detail


# --------------------------------------------------------------------------- teams
class _FakeResponse:
    def __init__(self, status: int, text: str = "1") -> None:
        self.status_code = status
        self.text = text


def _fake_client_factory(status: int, text: str, log: list):
    class _FakeClient:
        def __init__(self, *a, **k) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def post(self, url, json=None, headers=None):
            log.append({"url": url, "json": json, "headers": headers})
            return _FakeResponse(status, text)

    return _FakeClient


def test_send_card_ok_and_failure(monkeypatch: pytest.MonkeyPatch, stage1_pkg: IncidentPackage, tmp_path: Path) -> None:
    card = build_stage1_card(stage1_pkg)
    settings = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), TEAMS_WEBHOOK_URL="https://teams.example.invalid/webhook/abc")

    log: list = []
    monkeypatch.setattr(teams_module.httpx, "Client", _fake_client_factory(200, "1", log))
    receipt = send_card(card, settings=settings)
    assert receipt.ok is True and receipt.channel == "teams"
    assert len(log) == 1
    assert log[0]["url"] == "https://teams.example.invalid/webhook/abc"
    assert log[0]["json"]["type"] == "message"
    assert log[0]["json"]["attachments"][0]["content"] == card
    assert "abc" not in (receipt.target or "")  # token never ends up in the receipt

    log.clear()
    monkeypatch.setattr(teams_module.httpx, "Client", _fake_client_factory(400, "Bad payload " * 50, log))
    receipt = send_card(card, settings=settings)
    assert receipt.ok is False
    assert receipt.detail.startswith("HTTP 400: ")
    assert len(receipt.detail) <= len("HTTP 400: ") + 200


def test_send_card_exception_is_a_receipt(monkeypatch: pytest.MonkeyPatch, stage1_pkg: IncidentPackage, tmp_path: Path) -> None:
    class _Boom:
        def __init__(self, *a, **k) -> None:
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(teams_module.httpx, "Client", _Boom)
    settings = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), TEAMS_WEBHOOK_URL="https://teams.example.invalid/webhook/abc")
    receipt = send_card(build_stage1_card(stage1_pkg), settings=settings)
    assert receipt.ok is False and "ConnectError" in receipt.detail


# --------------------------------------------------------------------------- outbox and deliver
def test_write_outbox(stage2_pkg: IncidentPackage, unconfigured: Settings, tmp_path: Path) -> None:
    card = build_stage2_card(stage2_pkg)
    subject, text, html = render_email(stage2_pkg)
    paths = write_outbox(INCIDENT_ID, "stage2", card, subject, text, html, package=stage2_pkg, settings=unconfigured)
    names = sorted(p.name for p in paths)
    assert names == sorted(
        ["stage2.card.json", "stage2.card.md", "stage2.card.html", "stage2.email.eml", "stage2.email.html", "stage2.package.json"]
    )
    for p in paths:
        assert p.exists() and p.parent == tmp_path / INCIDENT_ID
    loaded = json.loads((tmp_path / INCIDENT_ID / "stage2.card.json").read_text(encoding="utf-8"))
    assert loaded == card
    pkg_back = IncidentPackage.model_validate_json((tmp_path / INCIDENT_ID / "stage2.package.json").read_text(encoding="utf-8"))
    assert pkg_back.incident_id == INCIDENT_ID and pkg_back.stage == "stage2"


def test_deliver_nothing_configured(stage1_pkg: IncidentPackage, unconfigured: Settings, tmp_path: Path) -> None:
    receipts = deliver(stage1_pkg, settings=unconfigured)
    assert len(receipts) == 4
    ok = [r for r in receipts if r.ok]
    assert len(ok) == 1 and ok[0].channel == "outbox" and ok[0].stage == "stage1"
    assert ok[0].artifact is not None and ok[0].artifact.endswith("stage1.card.json")
    assert Path(ok[0].artifact).exists()
    not_ok = {r.channel: r for r in receipts if not r.ok}
    assert set(not_ok) == {"teams", "email", "servicenow"}
    assert not_ok["servicenow"].detail.startswith("not configured: set SERVICENOW_INSTANCE")
    assert not_ok["teams"].detail == "not configured: set TEAMS_WEBHOOK_URL"
    assert not_ok["email"].detail.startswith("not configured: set SMTP_HOST")
    folder = tmp_path / INCIDENT_ID
    for name in ("stage1.card.json", "stage1.card.md", "stage1.card.html", "stage1.email.eml", "stage1.email.html", "stage1.package.json"):
        assert (folder / name).exists(), name


def test_deliver_with_teams_calls_webhook_once(monkeypatch: pytest.MonkeyPatch, stage2_pkg: IncidentPackage, tmp_path: Path) -> None:
    log: list = []
    monkeypatch.setattr(teams_module.httpx, "Client", _fake_client_factory(200, "1", log))
    settings = Settings(_env_file=None, OPSAGENT_OUTBOX_DIR=str(tmp_path), TEAMS_WEBHOOK_URL="https://teams.example.invalid/webhook/xyz")
    receipts = deliver(stage2_pkg, settings=settings)
    assert len(log) == 1
    assert log[0]["json"]["attachments"][0]["content"]["type"] == "AdaptiveCard"
    assert "ORDER_CACHE" in json.dumps(log[0]["json"])
    by_channel = {r.channel: r for r in receipts}
    assert by_channel["outbox"].ok and by_channel["teams"].ok and not by_channel["email"].ok
    assert all(r.stage == "stage2" for r in receipts)
    assert (tmp_path / INCIDENT_ID / "stage2.card.json").exists()


def test_deliver_delay_notice(unconfigured: Settings, tmp_path: Path) -> None:
    receipts = deliver_delay_notice(INCIDENT_ID, SERVICE, "critical", 305.0, settings=unconfigured)
    assert [r.stage for r in receipts] == ["delay"] * 4
    ok = [r for r in receipts if r.ok]
    assert len(ok) == 1 and ok[0].channel == "outbox"
    assert (tmp_path / INCIDENT_ID / "delay.card.json").exists()
    assert (tmp_path / INCIDENT_ID / "delay.email.eml").exists()
