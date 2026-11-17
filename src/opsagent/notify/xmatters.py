"""xMatters on-call paging through a workflow trigger URL and the xMatters REST API (xM API).

Stage 1 POSTs the trigger URL (a Flow Designer HTTP trigger, or the inbound integration URL of a Create Event form).
That raises an xMatters event and pages the recipients. xMatters answers with a requestId; the sender keeps it in the
incident's outbox folder (xmatters.json) and later resolves it to the event id with GET /api/xm/1/events?requestId=.
Stage 2, the delay notice and the closure add annotations (comments) to that event, and the closure can terminate it
so the page stops. Without xM API credentials only the trigger URL is usable: stage 2 and the delay notice then raise
a follow-up event that carries the same incident id and a `stage` property; the closure reports that it could not
annotate. Never raises: every outcome is a DeliveryReceipt.

Payload shape (Create Event form convention, also easy to map in an HTTP trigger):
    {"properties": {incident_id, event_id, stage, severity, service, instance_id, summary, details, brand, trace_url},
     "priority": "HIGH" | "MEDIUM" | "LOW",            # from the severity policy (xmatters block)
     "recipients": [{"id": "Platform On-call"}]}         # XMATTERS_RECIPIENTS (names or uuids), optional

A form whose layout uses other property names takes XMATTERS_PROPERTIES ("summary=Summary,details=Message" for the
stock Send Alert form, triggered at /api/xm/1/forms/<form id>/triggers): only the mapped keys are sent, renamed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from opsagent.config import Settings, get_settings
from opsagent.notify.outbox import incident_dir
from opsagent.schemas.incident import DeliveryReceipt, IncidentPackage

NOT_CONFIGURED = "not configured: set XMATTERS_TRIGGER_URL (and XMATTERS_USER/XMATTERS_PASSWORD for annotations and termination)"
STATE_FILE = "xmatters.json"
_API = "/api/xm/1"
MAX_DETAILS_CHARS = 4000
MAX_COMMENT_CHARS = 1000  # xMatters rejects longer annotation comments (HTTP 400)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _receipt(stage: str, ok: bool, detail: str, target: str | None = None) -> DeliveryReceipt:
    return DeliveryReceipt(channel="xmatters", stage=stage, ok=ok, detail=detail[:500], target=target, sent_at=_now())  # type: ignore[arg-type]


class XMattersError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ client
class XMattersClient:
    """Trigger URL for raising events; xM API (basic auth: a REST user or an API key id and secret) for the rest."""

    def __init__(self, settings: Settings | None = None, timeout: float = 20.0):
        s = settings or get_settings()
        self.trigger_url = s.xmatters_trigger_url.strip()
        self.base = s.xmatters_base_url
        self.timeout = timeout
        self.auth: tuple[str, str] | None = (s.xmatters_user, s.xmatters_password) if s.xmatters_api_enabled else None
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, headers=self.headers, auth=self.auth)

    @staticmethod
    def _json(resp: httpx.Response) -> Any:
        if resp.status_code >= 300:
            raise XMattersError(f"HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise XMattersError(f"HTTP {resp.status_code}: non-JSON body") from exc

    def trigger(self, payload: dict) -> str:
        """POST the trigger URL; returns the requestId xMatters assigns to the inbound request."""
        with self._client() as client:
            data = self._json(client.post(self.trigger_url, json=payload))
        request_id = data.get("requestId") if isinstance(data, dict) else None
        if not request_id:
            raise XMattersError(f"trigger accepted but no requestId in response: {str(data)[:200]}")
        return str(request_id)

    def find_event(self, request_id: str) -> dict | None:
        with self._client() as client:
            data = self._json(client.get(f"{self.base}{_API}/events", params={"requestId": request_id}))
        items = data.get("data") if isinstance(data, dict) else None
        return items[0] if isinstance(items, list) and items else None

    def annotate(self, event_id: str, comment: str) -> dict:
        with self._client() as client:
            return self._json(client.post(f"{self.base}{_API}/events/{event_id}/annotations", json={"comment": clamp(comment)}))

    def terminate(self, event_id: str) -> dict:
        with self._client() as client:
            return self._json(client.post(f"{self.base}{_API}/events", json={"id": event_id, "status": "TERMINATED"}))

    def event_url(self, event_id: str) -> str:
        return f"{self.base}{_API}/events/{event_id}"

    def trigger_target(self) -> str:
        """Scheme and host only, so a receipt never carries an apiKey that may be embedded in the trigger URL."""
        try:
            u = httpx.URL(self.trigger_url)
            return f"{u.scheme}://{u.host}/..."
        except Exception:  # noqa: BLE001
            return "xmatters-trigger"


# ------------------------------------------------------------------------------------------------ per-incident state
def _state_path(incident_id: str, settings: Settings) -> Path:
    return incident_dir(incident_id, settings) / STATE_FILE


def load_state(incident_id: str, settings: Settings | None = None) -> dict:
    p = _state_path(incident_id, settings or get_settings())
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(incident_id: str, state: dict, settings: Settings | None = None) -> Path:
    p = _state_path(incident_id, settings or get_settings())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------------ payloads
def map_properties(props: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Rename / restrict the payload properties to what the target form's layout defines (XMATTERS_PROPERTIES)."""
    mapping = settings.xmatters_property_map
    if not mapping:
        return props
    mapped = {name: props[key] for key, name in mapping.items() if key in props}
    if not mapped:
        raise XMattersError(f"XMATTERS_PROPERTIES maps none of the payload keys ({', '.join(sorted(props))})")
    return mapped


def _recipients(settings: Settings) -> list[dict]:
    # "id" takes a uuid or a target name; a form trigger silently ignores recipients given as "targetName"
    names = [n.strip() for n in settings.xmatters_recipients.split(",") if n.strip()]
    return [{"id": n} for n in names]


def event_payload(pkg: IncidentPackage, body: str, settings: Settings, priority: str) -> dict:
    sev = (pkg.severity or "info").lower()
    props: dict[str, Any] = {
        "incident_id": pkg.incident_id,
        "event_id": pkg.event_id,
        "stage": pkg.stage,
        "severity": sev,
        "service": pkg.service_name,
        "instance_id": pkg.instance_id,
        "summary": f"[{sev.upper()}] {pkg.title}",
        "details": _details(pkg.incident_id, pkg.stage, body, pkg.trace_url),
        "brand": pkg.brand,
        "trace_url": pkg.trace_url or "",
    }
    payload: dict[str, Any] = {"properties": map_properties(props, settings), "priority": priority}
    recipients = _recipients(settings)
    if recipients:
        payload["recipients"] = recipients
    return payload


def follow_up_payload(incident_id: str, stage: str, severity: str, text: str, settings: Settings, priority: str) -> dict:
    """A later-stage event for accounts without xM API credentials (no annotations possible)."""
    label = {"stage2": "diagnosis", "delay": "delay notice", "closure": "closure"}.get(stage, stage)
    props = {
        "incident_id": incident_id,
        "stage": stage,
        "severity": severity,
        "summary": f"[{severity.upper()}] {incident_id}: {label}",
        "details": _details(incident_id, stage, text, None),
        "brand": settings.brand,
    }
    payload: dict[str, Any] = {"properties": map_properties(props, settings), "priority": priority}
    recipients = _recipients(settings)
    if recipients:
        payload["recipients"] = recipients
    return payload


def _details(incident_id: str, stage: str, body: str, trace_url: str | None) -> str:
    """Message body that stands on its own when the form carries only a summary and a message."""
    head = f"OpsAgent incident {incident_id} ({stage})"
    tail = f"\n\nRun recorder: {trace_url}" if trace_url else ""
    room = MAX_DETAILS_CHARS - len(head) - len(tail) - 2
    return f"{head}\n\n{body[:max(room, 0)]}{tail}"


def clamp(text: str, limit: int = MAX_COMMENT_CHARS) -> str:
    """Fit a comment into xMatters' annotation limit, cutting at a line break when one is near the end."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    nl = cut.rfind("\n")
    if nl > limit * 0.6:
        cut = cut[:nl]
    return cut.rstrip() + "..."


def stage_comment(pkg: IncidentPackage, body: str) -> str:
    """A digest that fits an annotation: the full card already went to the ticket, email and outbox."""
    if pkg.stage != "stage2":
        return clamp(f"Stage 1 of 2: triage for {pkg.incident_id}\n{pkg.headline}\n\n{pkg.summary}")
    lines = [f"Stage 2 of 2: diagnosis for {pkg.incident_id}", pkg.headline]
    d, c = pkg.diagnosis, pkg.code_correlation
    if d is not None:
        lines.append(f"Root cause ({d.root_cause.category}, {d.root_cause.confidence}): {d.root_cause.summary}")
    if c is not None:
        where = f" at {c.locations[0].file}" + (f"::{c.locations[0].symbol}" if c.locations[0].symbol else "") if c.locations else ""
        lines.append(f"Code verdict: {c.verdict} ({c.confidence:.0%}){where}. {c.developer_action}")
    if pkg.recommended_fix is not None:
        lines.append(f"Immediate fix: {pkg.recommended_fix.detail}")
    if pkg.durable_fix is not None:
        lines.append(f"Durable fix: {pkg.durable_fix.detail}")
    if not d and not c:
        lines.append(body)
    if pkg.trace_url:
        lines.append(f"Full report: {pkg.trace_url}")
    return clamp("\n".join(lines))


# ------------------------------------------------------------------------------------------------ helpers
def _priority_for(severity: str) -> str:
    from opsagent.parsing.severity_policy import get_policy

    return get_policy().event_priority((severity or "info").lower())


def _resolve_event(client: XMattersClient, incident_id: str, state: dict, settings: Settings) -> str | None:
    """The xMatters event id for this incident: cached in state, else looked up by the stage 1 requestId."""
    if state.get("event_id"):
        return str(state["event_id"])
    request_id = state.get("request_id")
    if not request_id or client.auth is None:
        return None
    event = client.find_event(str(request_id))
    if not event:
        return None
    event_id = str(event.get("id") or event.get("eventId") or "")
    if not event_id:
        return None
    state["event_id"] = event_id
    state["event_number"] = event.get("eventId")
    save_state(incident_id, state, settings)
    return event_id


def _raise_event(client: XMattersClient, incident_id: str, payload: dict, stage: str, settings: Settings, state: dict, kind: str) -> DeliveryReceipt:
    request_id = client.trigger(payload)
    record = {"stage": stage, "request_id": request_id, "at": _now().isoformat()}
    if kind == "event":
        state.update({"request_id": request_id, "event_id": None, "priority": payload.get("priority"), "raised_at": record["at"]})
    state.setdefault("requests", []).append(record)
    save_state(incident_id, state, settings)
    what = "event requested" if kind == "event" else "follow-up event requested"
    return _receipt(stage, True, f"{what} (requestId {request_id}, priority {payload.get('priority')})", client.trigger_target())


# ------------------------------------------------------------------------------------------------ senders
def send_stage(pkg: IncidentPackage, body: str, settings: Settings | None = None) -> DeliveryReceipt:
    """Stage 1 raises the event; stage 2 annotates it (or raises a follow-up event when it cannot)."""
    s = settings or get_settings()
    if not s.xmatters_enabled:
        return _receipt(pkg.stage, False, NOT_CONFIGURED)
    try:
        client = XMattersClient(s)
        state = load_state(pkg.incident_id, s)
        priority = _priority_for(pkg.severity)
        if pkg.stage == "stage1" or not state.get("request_id"):
            return _raise_event(client, pkg.incident_id, event_payload(pkg, body, s, priority), pkg.stage, s, state, "event")
        event_id = _resolve_event(client, pkg.incident_id, state, s)
        if event_id is None:
            payload = follow_up_payload(pkg.incident_id, pkg.stage, (pkg.severity or "info").lower(), stage_comment(pkg, body), s, priority)
            return _raise_event(client, pkg.incident_id, payload, pkg.stage, s, state, "follow-up")
        client.annotate(event_id, stage_comment(pkg, body))
        return _receipt(pkg.stage, True, f"annotated event {state.get('event_number') or event_id}: diagnosis added", client.event_url(event_id))
    except Exception as exc:  # noqa: BLE001 - delivery must never take the flow down
        return _receipt(pkg.stage, False, f"{type(exc).__name__}: {exc}")


def send_note(incident_id: str, text: str, stage: str, severity: str = "critical", settings: Settings | None = None, terminate: bool = False) -> DeliveryReceipt:
    """Delay notice or closure. Annotates the event; the closure terminates it when asked. A delay notice that
    cannot be annotated becomes a follow-up event; a closure that cannot be annotated is reported, not paged."""
    s = settings or get_settings()
    if not s.xmatters_enabled:
        return _receipt(stage, False, NOT_CONFIGURED)
    try:
        client = XMattersClient(s)
        state = load_state(incident_id, s)
        if not state.get("request_id"):
            return _receipt(stage, False, f"no xMatters event was raised for {incident_id}")
        event_id = _resolve_event(client, incident_id, state, s)
        if event_id is None:
            if stage == "delay":
                payload = follow_up_payload(incident_id, stage, severity, text, s, _priority_for(severity))
                return _raise_event(client, incident_id, payload, stage, s, state, "follow-up")
            why = "xM API credentials are not set" if client.auth is None else "the event is not visible yet"
            return _receipt(stage, False, f"could not annotate the xMatters event for {incident_id}: {why}")
        client.annotate(event_id, text)
        number = state.get("event_number") or event_id
        if terminate:
            client.terminate(event_id)
            state["terminated_at"] = _now().isoformat()
            save_state(incident_id, state, s)
            return _receipt(stage, True, f"annotated and terminated event {number}", client.event_url(event_id))
        return _receipt(stage, True, f"annotated event {number}: {stage} note added", client.event_url(event_id))
    except Exception as exc:  # noqa: BLE001
        return _receipt(stage, False, f"{type(exc).__name__}: {exc}")
