"""ServiceNow ITSM delivery through the Table API.

Stage 1 opens an incident record (correlation_id = the OpsAgent incident id). Stage 2, the delay notice and the
closure look the record up by that correlation id and add a work note, so the whole lifecycle lands on one ticket.
Never raises: every outcome is a DeliveryReceipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from opsagent.config import Settings, get_settings
from opsagent.schemas.incident import DeliveryReceipt, IncidentPackage

NOT_CONFIGURED = "not configured: set SERVICENOW_INSTANCE and SERVICENOW_USER/SERVICENOW_PASSWORD (or SERVICENOW_TOKEN)"
CORRELATION_DISPLAY = "OpsAgent"
_TABLE = "/api/now/table/incident"

# ServiceNow priority is derived from impact x urgency (1 = high, 3 = low)
_PRIORITY: dict[str, tuple[str, str]] = {"critical": ("1", "1"), "warning": ("2", "2"), "info": ("3", "3")}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _receipt(stage: str, ok: bool, detail: str, target: str | None = None) -> DeliveryReceipt:
    return DeliveryReceipt(channel="servicenow", stage=stage, ok=ok, detail=detail[:500], target=target, sent_at=_now())  # type: ignore[arg-type]


class ServiceNowError(RuntimeError):
    pass


class ServiceNowClient:
    """Thin Table API client: find by correlation id, create, update. Basic auth or a bearer token."""

    def __init__(self, settings: Settings | None = None, timeout: float = 30.0):
        s = settings or get_settings()
        self.base = s.servicenow_base_url
        self.timeout = timeout
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        self.auth: tuple[str, str] | None = None
        if s.servicenow_token.strip():
            self.headers["Authorization"] = f"Bearer {s.servicenow_token.strip()}"
        else:
            self.auth = (s.servicenow_user, s.servicenow_password)

    def record_url(self, sys_id: str) -> str:
        return f"{self.base}/nav_to.do?uri=incident.do?sys_id={sys_id}"

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, headers=self.headers, auth=self.auth)

    @staticmethod
    def _result(resp: httpx.Response) -> Any:
        if resp.status_code >= 300:
            raise ServiceNowError(f"HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        try:
            return resp.json().get("result")
        except Exception as exc:  # noqa: BLE001
            raise ServiceNowError(f"HTTP {resp.status_code}: non-JSON body") from exc

    def find_by_correlation(self, incident_id: str) -> dict | None:
        params = {
            "sysparm_query": f"correlation_id={incident_id}^ORDERBYDESCsys_created_on",
            "sysparm_fields": "sys_id,number,state,priority",
            "sysparm_limit": "1",
        }
        with self._client() as client:
            result = self._result(client.get(f"{self.base}{_TABLE}", params=params))
        return result[0] if isinstance(result, list) and result else None

    def create(self, fields: dict) -> dict:
        with self._client() as client:
            return self._result(client.post(f"{self.base}{_TABLE}", json=fields, params={"sysparm_fields": "sys_id,number,priority"}))

    def update(self, sys_id: str, fields: dict) -> dict:
        with self._client() as client:
            return self._result(client.patch(f"{self.base}{_TABLE}/{sys_id}", json=fields, params={"sysparm_fields": "sys_id,number,priority"}))


# ------------------------------------------------------------------------------------------------ field mapping
def incident_fields(pkg: IncidentPackage, body: str, settings: Settings) -> dict:
    """Fields for a new incident record built from the package (stage 1 normally; stage 2 when stage 1 never landed)."""
    impact, urgency = _PRIORITY.get((pkg.severity or "info").lower(), ("3", "3"))
    fields: dict[str, Any] = {
        "short_description": f"[{(pkg.severity or 'info').upper()}] {pkg.title}"[:160],
        "description": body,
        "impact": impact,
        "urgency": urgency,
        "category": settings.servicenow_category or "software",
        "correlation_id": pkg.incident_id,
        "correlation_display": CORRELATION_DISPLAY,
        "contact_type": "monitoring",
        "work_notes": f"Opened by {pkg.brand} OpsAgent from event {pkg.event_id} ({pkg.stage}).",
    }
    if settings.servicenow_assignment_group.strip():
        fields["assignment_group"] = settings.servicenow_assignment_group.strip()
    if settings.servicenow_caller_id.strip():
        fields["caller_id"] = settings.servicenow_caller_id.strip()
    return fields


def stage_work_note(pkg: IncidentPackage, body: str) -> str:
    label = "Stage 2 of 2: diagnosis" if pkg.stage == "stage2" else "Stage 1 of 2: triage"
    return f"{pkg.brand} OpsAgent, {label} for {pkg.incident_id}\n\n{body}"


# ------------------------------------------------------------------------------------------------ senders
def send_stage(pkg: IncidentPackage, body: str, settings: Settings | None = None) -> DeliveryReceipt:
    """Stage 1 creates the record; stage 2 adds the diagnosis as a work note to the record stage 1 created."""
    s = settings or get_settings()
    if not s.servicenow_enabled:
        return _receipt(pkg.stage, False, NOT_CONFIGURED)
    try:
        client = ServiceNowClient(s)
        existing = client.find_by_correlation(pkg.incident_id)
        if existing is None:
            try:
                rec = client.create(incident_fields(pkg, body, s))
            except httpx.TimeoutException:
                # a developer instance waking from hibernation can take longer than the timeout to answer the POST
                # while still committing the record; look it up before declaring the create lost
                rec = client.find_by_correlation(pkg.incident_id)
                if rec is None:
                    raise
            verb = "created"
            if pkg.stage == "stage2":
                rec = client.update(rec["sys_id"], {"work_notes": stage_work_note(pkg, body)}) or rec
                verb = "created (stage 1 record was missing) and updated"
        else:
            rec = client.update(existing["sys_id"], {"work_notes": stage_work_note(pkg, body)}) or existing
            verb = "updated"
        number = rec.get("number") or existing and existing.get("number") or "incident"
        sys_id = rec.get("sys_id") or (existing or {}).get("sys_id", "")
        priority = rec.get("priority")
        detail = f"{verb} {number}" + (f" (priority {priority})" if priority else "") + (": work note added" if verb.startswith("updated") else "")
        return _receipt(pkg.stage, True, detail, client.record_url(sys_id))
    except Exception as exc:  # noqa: BLE001 - delivery must never take the flow down
        return _receipt(pkg.stage, False, f"{type(exc).__name__}: {exc}")


def send_work_note(incident_id: str, text: str, stage: str, settings: Settings | None = None, resolve: bool = False) -> DeliveryReceipt:
    """Add a work note (delay notice or closure) to the record opened for this incident id."""
    s = settings or get_settings()
    if not s.servicenow_enabled:
        return _receipt(stage, False, NOT_CONFIGURED)
    try:
        client = ServiceNowClient(s)
        existing = client.find_by_correlation(incident_id)
        if existing is None:
            return _receipt(stage, False, f"no ServiceNow record carries correlation_id {incident_id}")
        fields: dict[str, Any] = {"work_notes": text}
        if resolve:
            # state 6 = Resolved; close code and notes are mandatory on most instances
            fields.update({"state": "6", "close_code": "Solved (Permanently)", "close_notes": text[:4000]})
        rec = client.update(existing["sys_id"], fields) or existing
        number = rec.get("number") or existing.get("number") or "incident"
        detail = f"{'resolved' if resolve else 'updated'} {number}: work note added"
        return _receipt(stage, True, detail, client.record_url(existing["sys_id"]))
    except Exception as exc:  # noqa: BLE001
        return _receipt(stage, False, f"{type(exc).__name__}: {exc}")
