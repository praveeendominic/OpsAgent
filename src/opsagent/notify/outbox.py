"""The outbox: every page is also written to disk so the demo can be shown from files."""
from __future__ import annotations

import json
import re
from pathlib import Path

from opsagent.config import Settings, get_settings
from opsagent.notify.cards import card_to_html, card_to_markdown
from opsagent.notify.email import build_eml
from opsagent.schemas.incident import IncidentPackage

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(value: str) -> str:
    cleaned = _SAFE.sub("_", value.strip()) or "incident"
    return cleaned[:120]


def incident_dir(incident_id: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return s.outbox_path / _safe_name(incident_id)


def write_outbox(
    incident_id: str,
    stage: str,
    card: dict,
    subject: str | None = None,
    text: str | None = None,
    html: str | None = None,
    package: IncidentPackage | None = None,
    settings: Settings | None = None,
) -> list[Path]:
    """Write <outbox>/<incident_id>/<stage>.card.json|md|html, the email files and the package. Returns the paths."""
    s = settings or get_settings()
    folder = incident_dir(incident_id, s)
    folder.mkdir(parents=True, exist_ok=True)
    stage = _safe_name(stage)
    written: list[Path] = []

    card_json = folder / f"{stage}.card.json"
    card_json.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(card_json)

    card_md = folder / f"{stage}.card.md"
    card_md.write_text(card_to_markdown(card), encoding="utf-8")
    written.append(card_md)

    card_html = folder / f"{stage}.card.html"
    card_html.write_text(card_to_html(card), encoding="utf-8")
    written.append(card_html)

    if subject is not None and (text is not None or html is not None):
        sender = s.smtp_from.strip() or "opsagent@example.invalid"
        to = s.smtp_to.strip() or "oncall@example.invalid"
        eml = folder / f"{stage}.email.eml"
        eml.write_bytes(build_eml(subject, text or "", html or "", sender=sender, to=to))
        written.append(eml)
        if html is not None:
            email_html = folder / f"{stage}.email.html"
            email_html.write_text(html, encoding="utf-8")
            written.append(email_html)

    if package is not None:
        pkg_path = folder / f"{stage}.package.json"
        pkg_path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
        written.append(pkg_path)

    return written
