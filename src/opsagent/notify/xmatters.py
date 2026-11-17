"""xMatters: a heads-up call to on-call, nothing more.

One event per incident, raised at stage 1 through a trigger URL: the stock Send Alert form of the instance
(/api/xm/1/forms/<form id>/triggers, basic auth) or a Flow Designer trigger. xMatters rings the recipients' phones with
a short spoken message (XMATTERS_DEVICES picks the devices: voice "Mobile Phone" / "Work Phone" on a paid plan, the
mobile app's push "Android Phone" / "iPhone" on the free plan, which has no voice or SMS devices) and runs its own
escalation (L1 Support first, L2 Support after five minutes, for example). Everything else, the stage 2 diagnosis, the
delay notice and the closure text, goes to the ticket, email, Teams and the outbox, not to xMatters. When the flow
closes it terminates the event (XMATTERS_TERMINATE_ON_CLOSE=1, the default) so an unanswered call stops retrying and
the escalation does not fire for an incident the agent has already handled. Never raises: every outcome is a
DeliveryReceipt.

Payload (the Send Alert form takes XMATTERS_PROPERTIES=summary=Summary,details=Message: only those two, renamed):
    {"properties": {incident_id, event_id, severity, service, instance_id, ticket, summary, details, brand, trace_url},
     "priority": "HIGH" | "MEDIUM" | "LOW",                 # severity policy, xmatters block
     "recipients": [{"id": "L1 Support"}],                   # XMATTERS_RECIPIENTS: names or uuids, in the id field
     "targetDeviceNames": ["Mobile Phone", "Work Phone"],    # XMATTERS_DEVICES; absent = every device, email included
     "voicemailOptions": {"retry": 0, "every": 60, "leave": "messageonly"}}  # unanswered: leave the heads-up
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

NOT_CONFIGURED = "not configured: set XMATTERS_TRIGGER_URL, XMATTERS_USER and XMATTERS_PASSWORD"
STATE_FILE = "xmatters.json"
_API = "/api/xm/1"
MAX_MESSAGE_CHARS = 2000
VOICEMAIL = {"retry": 0, "every": 60, "leave": "messageonly"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _receipt(stage: str, ok: bool, detail: str, target: str | None = None) -> DeliveryReceipt:
    return DeliveryReceipt(channel="xmatters", stage=stage, ok=ok, detail=detail[:500], target=target, sent_at=_now())  # type: ignore[arg-type]


class XMattersError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ client
class XMattersClient:
    """Trigger URL for raising the event; xM API (basic auth: a REST user or an API key id and secret) to end it."""

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

    def trigger(self, payload: dict) -> dict:
        """POST the trigger URL. A form trigger answers with the event itself (id, eventId, requestId); a Flow Designer
        trigger answers with a requestId only, resolved to the event later through GET /events?requestId=."""
        with self._client() as client:
            data = self._json(client.post(self.trigger_url, json=payload))
        if not isinstance(data, dict) or not (data.get("id") or data.get("requestId")):
            raise XMattersError(f"trigger accepted but returned neither an event id nor a requestId: {str(data)[:200]}")
        return data

    def find_event(self, request_id: str) -> dict | None:
        with self._client() as client:
            data = self._json(client.get(f"{self.base}{_API}/events", params={"requestId": request_id}))
        items = data.get("data") if isinstance(data, dict) else None
        return items[0] if isinstance(items, list) and items else None

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


# ------------------------------------------------------------------------------------------------ payload
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


MIN_HEADLINE_CHARS = 30  # below this the headline is a label ("process oom kill"), not a sentence worth saying
MAX_WHAT_CHARS = 260


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _what_happened(pkg: IncidentPackage) -> str:
    """One sentence on what happened: the headline when it says something, else the first sentence of the triage
    summary (the analyst's one-paragraph account), cut at a word when it runs long."""
    headline = pkg.short_headline.strip()
    if len(headline) >= MIN_HEADLINE_CHARS or not pkg.summary.strip():
        return _sentence(headline)
    first = " ".join(pkg.summary.split())
    for stop in (". ", "; "):
        if stop in first:
            first = first.split(stop, 1)[0]
            break
    if len(first) > MAX_WHAT_CHARS:
        first = first[:MAX_WHAT_CHARS].rsplit(" ", 1)[0]
    return _sentence(first)


def spoken_message(pkg: IncidentPackage, ticket: str | None = None) -> str:
    """Short plain sentences: xMatters reads the message aloud on a phone and shows it as text on other devices.
    No markdown, no links, no incident id (a 17-character token read digit by digit); the ticket number instead."""
    sev = (pkg.severity or "info").lower()
    lines = [
        f"{pkg.brand} OpsAgent heads-up.",
        f"A {sev} incident is open on {pkg.service_name}.",
        _what_happened(pkg),
    ]
    if ticket:
        lines.append(f"ServiceNow ticket {ticket} has the stage one report.")
    else:
        lines.append("The stage one report is on its way.")
    lines.append("The diagnosis follows there in a minute or two.")
    return " ".join(lines)[:MAX_MESSAGE_CHARS]


def headsup_payload(pkg: IncidentPackage, settings: Settings, priority: str, ticket: str | None = None) -> dict:
    sev = (pkg.severity or "info").lower()
    props: dict[str, Any] = {
        "incident_id": pkg.incident_id,
        "event_id": pkg.event_id,
        "severity": sev,
        "service": pkg.service_name,
        "instance_id": pkg.instance_id,
        "ticket": ticket or "",
        "summary": f"{pkg.brand} OpsAgent heads-up: {sev} incident on {pkg.service_name}",
        "details": spoken_message(pkg, ticket),
        "brand": pkg.brand,
        "trace_url": pkg.trace_url or "",
    }
    payload: dict[str, Any] = {"properties": map_properties(props, settings), "priority": priority, "voicemailOptions": dict(VOICEMAIL)}
    recipients = _recipients(settings)
    if recipients:
        payload["recipients"] = recipients
    devices = settings.xmatters_device_names
    if devices:
        payload["targetDeviceNames"] = devices
    return payload


# ------------------------------------------------------------------------------------------------ helpers
def _priority_for(severity: str) -> str:
    from opsagent.parsing.severity_policy import get_policy

    return get_policy().event_priority((severity or "info").lower())


def _resolve_event(client: XMattersClient, incident_id: str, state: dict, settings: Settings) -> str | None:
    """The xMatters event uuid for this incident: cached in state, else looked up by the trigger's requestId."""
    if state.get("event_id"):
        return str(state["event_id"])
    request_id = state.get("request_id")
    if not request_id or client.auth is None:
        return None
    event = client.find_event(str(request_id))
    if not event:
        return None
    event_id = str(event.get("id") or "")
    if not event_id:
        return None
    state["event_id"] = event_id
    state["event_number"] = event.get("eventId")
    save_state(incident_id, state, settings)
    return event_id


# ------------------------------------------------------------------------------------------------ senders
def send_headsup(pkg: IncidentPackage, settings: Settings | None = None, ticket: str | None = None) -> DeliveryReceipt:
    """Stage 1: raise the event that rings on-call. One per incident: a repeat for the same incident id is reported,
    not placed. `ticket` is the ITSM record number to say in the message when the ticket channel created one."""
    s = settings or get_settings()
    if not s.xmatters_enabled:
        return _receipt(pkg.stage, False, NOT_CONFIGURED)
    try:
        client = XMattersClient(s)
        state = load_state(pkg.incident_id, s)
        if state.get("event_id") or state.get("request_id"):
            number = state.get("event_number") or state.get("request_id")
            return _receipt(pkg.stage, True, f"heads-up already placed for {pkg.incident_id} (event {number})",
                            client.event_url(state["event_id"]) if state.get("event_id") else client.trigger_target())
        payload = headsup_payload(pkg, s, _priority_for(pkg.severity), ticket)
        data = client.trigger(payload)
        event_id = str(data.get("id") or "") or None
        state = {
            "request_id": data.get("requestId"),
            "event_id": event_id,
            "event_number": data.get("eventId"),
            "priority": payload["priority"],
            "recipients": [r["id"] for r in payload.get("recipients", [])],
            "devices": payload.get("targetDeviceNames") or "all",
            "ticket": ticket,
            "raised_at": _now().isoformat(),
        }
        save_state(pkg.incident_id, state, s)
        who = ", ".join(state["recipients"]) or "the form's recipients"
        ring = ", ".join(payload.get("targetDeviceNames") or []) or "every device"
        number = state["event_number"] or f"requestId {state['request_id']}"
        return _receipt(pkg.stage, True, f"heads-up event {number} raised (priority {payload['priority']}) for {who} on {ring}",
                        client.event_url(event_id) if event_id else client.trigger_target())
    except Exception as exc:  # noqa: BLE001 - delivery must never take the flow down
        return _receipt(pkg.stage, False, f"{type(exc).__name__}: {exc}")


def close_event(incident_id: str, settings: Settings | None = None) -> DeliveryReceipt:
    """Closure: terminate the heads-up event so an unanswered call stops retrying and the escalation does not fire."""
    s = settings or get_settings()
    if not s.xmatters_enabled:
        return _receipt("closure", False, NOT_CONFIGURED)
    try:
        client = XMattersClient(s)
        state = load_state(incident_id, s)
        if not (state.get("event_id") or state.get("request_id")):
            return _receipt("closure", False, f"no xMatters heads-up was placed for {incident_id}")
        if client.auth is None:
            return _receipt("closure", False, "cannot terminate the xMatters event: XMATTERS_USER / XMATTERS_PASSWORD not set")
        event_id = _resolve_event(client, incident_id, state, s)
        if event_id is None:
            return _receipt("closure", False, f"the xMatters event for {incident_id} is not visible yet (requestId {state.get('request_id')})")
        client.terminate(event_id)
        state["terminated_at"] = _now().isoformat()
        save_state(incident_id, state, s)
        number = state.get("event_number") or event_id
        return _receipt("closure", True, f"terminated heads-up event {number}: call retries and escalation stopped", client.event_url(event_id))
    except Exception as exc:  # noqa: BLE001
        return _receipt("closure", False, f"{type(exc).__name__}: {exc}")
