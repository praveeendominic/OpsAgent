"""Deliver an IncidentPackage: outbox always, then Teams, email, ServiceNow and xMatters when configured."""
from __future__ import annotations

from datetime import datetime, timezone

from opsagent.config import Settings, get_settings
from opsagent.notify.cards import (
    build_delay_card,
    build_stage1_card,
    build_stage2_card,
    card_to_html,
    card_to_markdown,
)
from opsagent.notify.email import render_email, send_email
from opsagent.notify.outbox import write_outbox
from opsagent.notify.servicenow import NOT_CONFIGURED as SERVICENOW_NOT_CONFIGURED
from opsagent.notify.servicenow import send_stage as servicenow_send_stage
from opsagent.notify.servicenow import send_work_note as servicenow_work_note
from opsagent.notify.teams import send_card
from opsagent.notify.xmatters import NOT_CONFIGURED as XMATTERS_NOT_CONFIGURED
from opsagent.notify.xmatters import send_note as xmatters_send_note
from opsagent.notify.xmatters import send_stage as xmatters_send_stage
from opsagent.schemas.incident import DeliveryReceipt, IncidentPackage

TEAMS_NOT_CONFIGURED = "not configured: set TEAMS_WEBHOOK_URL"
EMAIL_NOT_CONFIGURED = "not configured: set SMTP_HOST, SMTP_FROM and SMTP_TO (and SMTP_USER/SMTP_PASSWORD when the relay needs login)"


def build_card(pkg: IncidentPackage) -> dict:
    return build_stage2_card(pkg) if pkg.stage == "stage2" else build_stage1_card(pkg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _outbox_receipt(stage: str, paths, error: Exception | None = None) -> DeliveryReceipt:
    if error is not None:
        return DeliveryReceipt(
            channel="outbox", stage=stage, ok=False, detail=f"{type(error).__name__}: {error}"[:500], sent_at=_now()  # type: ignore[arg-type]
        )
    card_json = next((p for p in paths if p.name.endswith(".card.json")), paths[0] if paths else None)
    return DeliveryReceipt(
        channel="outbox",
        stage=stage,  # type: ignore[arg-type]
        ok=True,
        detail=f"{len(paths)} file(s) written",
        target=str(card_json.parent) if card_json else None,
        artifact=str(card_json) if card_json else None,
        sent_at=_now(),
    )


def _not_configured(channel: str, stage: str, detail: str) -> DeliveryReceipt:
    return DeliveryReceipt(channel=channel, stage=stage, ok=False, detail=detail, sent_at=_now())  # type: ignore[arg-type]


def _fan_out(
    card: dict,
    stage: str,
    s: Settings,
    email_parts: tuple[str, str, str] | None,
    pkg: IncidentPackage | None = None,
    note: tuple[str, str] | None = None,
    severity: str = "critical",
) -> list[DeliveryReceipt]:
    """Teams, email, ServiceNow and xMatters. A package creates/updates the ServiceNow record and raises/annotates
    the xMatters event; a (incident_id, text) note is appended to both as a work note / annotation."""
    receipts: list[DeliveryReceipt] = []
    if s.teams_enabled:
        receipts.append(send_card(card, settings=s, stage=stage))
    else:
        receipts.append(_not_configured("teams", stage, TEAMS_NOT_CONFIGURED))
    if email_parts is not None:
        if s.email_enabled:
            subject, text, html = email_parts
            receipts.append(send_email(subject, text, html, settings=s, stage=stage))
        else:
            receipts.append(_not_configured("email", stage, EMAIL_NOT_CONFIGURED))
    if s.servicenow_enabled:
        if pkg is not None:
            receipts.append(servicenow_send_stage(pkg, card_to_markdown(card), settings=s))
        elif note is not None:
            receipts.append(servicenow_work_note(note[0], note[1], stage, settings=s))
    else:
        receipts.append(_not_configured("servicenow", stage, SERVICENOW_NOT_CONFIGURED))
    if s.xmatters_enabled:
        if pkg is not None:
            receipts.append(xmatters_send_stage(pkg, card_to_markdown(card), settings=s))
        elif note is not None:
            receipts.append(xmatters_send_note(note[0], note[1], stage, severity=severity, settings=s))
    else:
        receipts.append(_not_configured("xmatters", stage, XMATTERS_NOT_CONFIGURED))
    return receipts


def deliver(pkg: IncidentPackage, settings: Settings | None = None) -> list[DeliveryReceipt]:
    """Build the stage card and email, write the outbox (always), then Teams and email when configured."""
    s = settings or get_settings()
    card = build_card(pkg)
    subject, text, html = render_email(pkg)
    receipts: list[DeliveryReceipt] = []
    try:
        paths = write_outbox(pkg.incident_id, pkg.stage, card, subject, text, html, package=pkg, settings=s)
        receipts.append(_outbox_receipt(pkg.stage, paths))
    except Exception as exc:  # noqa: BLE001 - the outbox must not take the flow down either
        receipts.append(_outbox_receipt(pkg.stage, [], error=exc))
    receipts.extend(_fan_out(card, pkg.stage, s, (subject, text, html), pkg=pkg))
    return receipts


def deliver_delay_notice(
    incident_id: str,
    service: str | None,
    severity: str,
    elapsed_s: float,
    settings: Settings | None = None,
    stage_pending: str = "stage2",
) -> list[DeliveryReceipt]:
    """Watchdog notice: the pending stage is late. Outbox always, Teams and email when configured."""
    s = settings or get_settings()
    card = build_delay_card(incident_id, service, severity, elapsed_s, stage_pending=stage_pending, brand=s.brand)
    subject = (
        f"[{(severity or 'info').upper()}] {service or 'unknown-service'}: diagnosis still running "
        f"({incident_id}, delay notice)"
    )
    text = card_to_markdown(card)
    html = card_to_html(card)
    receipts: list[DeliveryReceipt] = []
    try:
        paths = write_outbox(incident_id, "delay", card, subject, text, html, settings=s)
        receipts.append(_outbox_receipt("delay", paths))
    except Exception as exc:  # noqa: BLE001
        receipts.append(_outbox_receipt("delay", [], error=exc))
    receipts.extend(_fan_out(card, "delay", s, (subject, text, html), note=(incident_id, text), severity=severity))
    return receipts


def deliver_closure(incident_id: str, kb_record, settings: Settings | None = None) -> list[DeliveryReceipt]:
    """Closure note for the ticketing and paging systems only: the knowledge record digest and the label workflow.
    Teams and email already carried the diagnosis; the ITSM record must show the closure and the xMatters event
    gets the same note and, by default, is terminated so the page stops."""
    s = settings or get_settings()
    lines = [
        f"{s.brand} OpsAgent closed its automated handling of {incident_id}.",
        "",
        f"Root cause: {kb_record.root_cause_summary}",
        f"Category: {kb_record.root_cause_category or 'n/a'}; code/infra verdict: {kb_record.verdict}"
        + (f" at {kb_record.code_location}" if kb_record.code_location else ""),
    ]
    if kb_record.immediate_fix:
        lines.append(f"Immediate fix: {kb_record.immediate_fix}")
    if kb_record.durable_fix:
        lines.append(f"Durable fix: {kb_record.durable_fix}")
    if kb_record.citations:
        lines.append("Citations: " + ", ".join(kb_record.citations[:5]))
    lines += ["", f"Knowledge record stored with label '{kb_record.label}'. "
              "Label the RCA (accepted / partially_correct / wrong) in the OpsAgent recorder so future incidents can reuse it."]
    text = "\n".join(lines)
    receipts: list[DeliveryReceipt] = []
    if s.servicenow_enabled:
        receipts.append(servicenow_work_note(incident_id, text, "closure", settings=s, resolve=s.servicenow_resolve_on_close))
    else:
        receipts.append(_not_configured("servicenow", "closure", SERVICENOW_NOT_CONFIGURED))
    if s.xmatters_enabled:
        receipts.append(xmatters_send_note(incident_id, text, "closure", severity=str(getattr(kb_record, "severity", "critical") or "critical"),
                                           settings=s, terminate=s.xmatters_terminate_on_close))
    else:
        receipts.append(_not_configured("xmatters", "closure", XMATTERS_NOT_CONFIGURED))
    return receipts
