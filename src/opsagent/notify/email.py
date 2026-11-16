"""Email rendering (Jinja2) and delivery (smtplib with STARTTLS) for the Incident Bridge."""
from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from opsagent.config import Settings, get_settings
from opsagent.notify.cards import _severity_colour, _triage_facts, _COLOUR_CSS
from opsagent.schemas.incident import DeliveryReceipt, IncidentPackage

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _stage_number(stage: str) -> int:
    return 2 if stage == "stage2" else 1


def _stage_label(stage: str) -> str:
    return "Stage 2 of 2: diagnosis" if stage == "stage2" else "Stage 1 of 2: triage"


def build_subject(pkg: IncidentPackage) -> str:
    return f"[{(pkg.severity or 'info').upper()}] {pkg.title} ({pkg.incident_id}, stage {_stage_number(pkg.stage)})"


def render_email(pkg: IncidentPackage) -> tuple[str, str, str]:
    """Return (subject, plain text, HTML) for the package's stage."""
    subject = build_subject(pkg)
    diag = pkg.diagnosis
    context = {
        "subject": subject,
        "brand": pkg.brand,
        "stage": pkg.stage,
        "stage_label": _stage_label(pkg.stage),
        "severity": (pkg.severity or "info").upper(),
        "severity_colour": _COLOUR_CSS.get(_severity_colour(pkg.severity), "#1f1f1f"),
        "service": pkg.service or pkg.triage.service or "unknown service",
        "instance_id": pkg.instance_id,
        "headline": pkg.headline,
        "summary": pkg.summary,
        "facts": _triage_facts(pkg),
        "diagnosis": diag,
        "code_correlation": pkg.code_correlation,
        "recommended_fix": pkg.recommended_fix or (diag.immediate_fix if diag else None),
        "durable_fix": pkg.durable_fix or (diag.durable_fix if diag else None),
        "trace_url": pkg.trace_url,
        "incident_id": pkg.incident_id,
        "event_id": pkg.event_id,
    }
    text = _env.get_template("stage.txt").render(**context)
    html = _env.get_template("stage.html").render(**context)
    return subject, text, html


def _build_message(subject: str, text: str, html: str, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="opsagent.local")
    msg["X-OpsAgent"] = "incident-bridge"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def build_eml(subject: str, text: str, html: str, sender: str = "opsagent@example.invalid", to: str = "oncall@example.invalid") -> bytes:
    """RFC 822 bytes of the multipart/alternative message, for the outbox."""
    recipients = [r.strip() for r in to.split(",") if r.strip()] or [to]
    return _build_message(subject, text, html, sender, recipients).as_bytes()


def _split_recipients(value: str) -> list[str]:
    return [r.strip() for r in value.replace(";", ",").split(",") if r.strip()]


def send_email(subject: str, text: str, html: str, settings: Settings | None = None, stage: str = "stage1") -> DeliveryReceipt:
    """Send over SMTP with STARTTLS. Never raises: failures become a receipt with ok False."""
    s = settings or get_settings()
    recipients = _split_recipients(s.smtp_to)
    now = datetime.now(timezone.utc)
    if not s.email_enabled:
        return DeliveryReceipt(
            channel="email",
            stage=stage,  # type: ignore[arg-type]
            ok=False,
            detail="not configured: set SMTP_HOST, SMTP_FROM and SMTP_TO (and SMTP_USER/SMTP_PASSWORD when the relay needs login)",
            target=s.smtp_to or None,
            sent_at=now,
        )
    try:
        msg = _build_message(subject, text, html, s.smtp_from, recipients)
        with smtplib.SMTP(s.smtp_host, int(s.smtp_port), timeout=20) as client:
            client.ehlo()
            try:
                client.starttls()
                client.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass  # plain relay without TLS (local dev relays)
            if s.smtp_user:
                client.login(s.smtp_user, s.smtp_password)
            client.send_message(msg, from_addr=s.smtp_from, to_addrs=recipients)
        return DeliveryReceipt(
            channel="email",
            stage=stage,  # type: ignore[arg-type]
            ok=True,
            detail=f"sent to {len(recipients)} recipient(s) via {s.smtp_host}:{s.smtp_port}",
            target=", ".join(recipients),
            sent_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - delivery must never take the flow down
        return DeliveryReceipt(
            channel="email",
            stage=stage,  # type: ignore[arg-type]
            ok=False,
            detail=f"{type(exc).__name__}: {exc}"[:500],
            target=", ".join(recipients) or None,
            sent_at=datetime.now(timezone.utc),
        )
