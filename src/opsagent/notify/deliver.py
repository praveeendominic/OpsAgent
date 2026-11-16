"""Deliver an IncidentPackage: outbox always, then Teams and email when configured."""
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
from opsagent.notify.teams import send_card
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
) -> list[DeliveryReceipt]:
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
    receipts.extend(_fan_out(card, pkg.stage, s, (subject, text, html)))
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
    receipts.extend(_fan_out(card, "delay", s, (subject, text, html)))
    return receipts
