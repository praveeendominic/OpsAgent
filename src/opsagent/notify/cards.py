"""Adaptive Card 1.5 builders for the Incident Bridge, plus plain-text/HTML renderings of a card."""
from __future__ import annotations

import html as _html
from datetime import datetime, timezone
from typing import Any

from opsagent.schemas.incident import IncidentPackage

SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
CARD_VERSION = "1.5"
MAX_CITATIONS = 5

_SEVERITY_COLOUR = {"critical": "attention", "warning": "warning", "info": "accent"}


# --------------------------------------------------------------------------- helpers
def _severity_colour(severity: str) -> str:
    return _SEVERITY_COLOUR.get((severity or "").lower(), "default")


def _fmt_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {rem:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def _time_since_alarm(pkg: IncidentPackage) -> str:
    key = pkg.stage
    if key in pkg.timings:
        return _fmt_elapsed(pkg.timings[key])
    fired = pkg.triage.alarm.fired_at
    created = pkg.created_at
    if fired.tzinfo is None and created.tzinfo is not None:
        fired = fired.replace(tzinfo=created.tzinfo)
    elif created.tzinfo is None and fired.tzinfo is not None:
        created = created.replace(tzinfo=fired.tzinfo)
    try:
        return _fmt_elapsed((created - fired).total_seconds())
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _text(text: str, **extra: Any) -> dict:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    block.update(extra)
    return block


def _heading(text: str) -> dict:
    return _text(text, weight="Bolder", size="Medium", spacing="Medium", separator=True)


def _fact(title: str, value: Any) -> dict:
    return {"title": str(title), "value": str(value)}


def _factset(facts: list[dict]) -> dict:
    return {"type": "FactSet", "facts": facts}


def _base_card(body: list[dict], actions: list[dict] | None = None) -> dict:
    return {
        "type": "AdaptiveCard",
        "$schema": SCHEMA_URL,
        "version": CARD_VERSION,
        "body": body,
        "actions": actions or [],
    }


def _header(pkg: IncidentPackage, stage_label: str) -> list[dict]:
    severity = (pkg.severity or "info").upper()
    service = pkg.service or pkg.triage.service or "unknown service"
    return [
        _text(f"{pkg.brand} | OpsAgent Incident Bridge | {stage_label}", size="Small", isSubtle=True),
        _text(
            f"{severity}: {service} on {pkg.instance_id}",
            size="Large",
            weight="Bolder",
            color=_severity_colour(pkg.severity),
        ),
        _text(pkg.short_headline, weight="Bolder"),
    ]


def _triage_facts(pkg: IncidentPackage) -> list[dict]:
    t = pkg.triage
    ev = t.evidence
    facts = [
        _fact("Incident", pkg.incident_id),
        _fact("Instance", pkg.instance_id),
        _fact("Service", pkg.service or t.service or "unknown"),
        _fact("Alarm", t.alarm.name),
        _fact("Severity", (pkg.severity or "info").upper()),
        _fact("Time since alarm", _time_since_alarm(pkg)),
        _fact("Classification", f"{t.classification.reason}/{t.classification.sub_reason} ({t.classification.confidence})"),
    ]
    if ev.leak_profile is not None:
        lp = ev.leak_profile
        facts.append(_fact("Leak slope", f"{lp.slope_mb_per_min:.0f} MB/min (peak {lp.peak_rss_mb:.0f} MB)"))
    restart = ev.restart_count
    if restart is None:
        counters = [e.restart_counter for e in ev.service_events if e.restart_counter is not None]
        restart = max(counters) if counters else None
    if restart is not None:
        facts.append(_fact("Restart counter", restart))
    if ev.oom_events:
        o = ev.oom_events[-1]
        rss = f"{o.anon_rss_kb // 1024} MB ({o.anon_rss_kb} kB)" if o.anon_rss_kb else "RSS unknown"
        facts.append(_fact("OOM kill", f"{o.killed_process} pid {o.killed_pid}, {rss}"))
    if t.owner:
        facts.append(_fact("Owner", t.owner))
    return facts


# --------------------------------------------------------------------------- public builders
def build_stage1_card(pkg: IncidentPackage) -> dict:
    """Stage 1: triage facts only, sent about a minute after the alarm."""
    body = _header(pkg, "Stage 1 of 2: triage")
    body.append(_factset(_triage_facts(pkg)))
    body.append(_text(pkg.summary, spacing="Medium"))
    if pkg.triage.analyst_note:
        body.append(_text(f"Analyst note: {pkg.triage.analyst_note}", isSubtle=True))
    body.append(
        _text(
            "Root cause, code verdict and the recommended fix follow in stage 2.",
            isSubtle=True,
            size="Small",
            spacing="Medium",
        )
    )
    actions: list[dict] = []
    if pkg.trace_url:
        actions.append({"type": "Action.OpenUrl", "title": "Open trace", "url": pkg.trace_url})
    return _base_card(body, actions)


def build_stage2_card(pkg: IncidentPackage) -> dict:
    """Stage 2: everything, once the root cause and the code verdict exist."""
    body = _header(pkg, "Stage 2 of 2: diagnosis")
    body.append(_factset(_triage_facts(pkg)))
    body.append(_text(pkg.summary, spacing="Medium"))

    diag = pkg.diagnosis
    if diag is not None:
        rc = diag.root_cause
        body.append(_heading("Root cause"))
        body.append(_text(rc.summary))
        rc_facts = [_fact("Category", rc.category), _fact("Confidence", rc.confidence)]
        if diag.classification_agreement != "agreed":
            rc_facts.append(_fact("Classification", diag.classification_agreement))
        body.append(_factset(rc_facts))
        if rc.contributing:
            body.append(_text("Contributing: " + "; ".join(rc.contributing), isSubtle=True))
        if diag.citations:
            body.append(_heading("Citations"))
            body.append(_factset([_fact(c.title, c.source) for c in diag.citations[:MAX_CITATIONS]]))

    cc = pkg.code_correlation
    if cc is not None:
        body.append(_heading("Code verdict"))
        facts = [_fact("Verdict", cc.verdict), _fact("Confidence", f"{cc.confidence:.0%}")]
        if cc.pattern and cc.pattern != "none":
            facts.append(_fact("Pattern", cc.pattern))
        if cc.repository:
            facts.append(_fact("Repository", cc.repository))
        for loc in cc.locations[:3]:
            where = f"{loc.file}:{loc.line}" if loc.line else loc.file
            if loc.symbol:
                where = f"{where} ({loc.symbol})"
            facts.append(_fact("Location", where))
        facts.append(_fact("Developer action", cc.developer_action))
        body.append(_factset(facts))
        if cc.explanation:
            body.append(_text(cc.explanation))

    fix = pkg.recommended_fix or (diag.immediate_fix if diag else None)
    if fix is not None:
        body.append(_heading("Recommended immediate fix"))
        body.append(_factset([_fact("Action", fix.action), _fact("Owner", fix.owner)]))
        body.append(_text(fix.detail))
        if fix.command:
            body.append(_text(fix.command, fontType="Monospace", wrap=True))
        if fix.reversal:
            body.append(_text(f"Reversal: {fix.reversal}", isSubtle=True, size="Small"))

    durable = pkg.durable_fix or (diag.durable_fix if diag else None)
    if durable is not None:
        body.append(_heading("Durable fix"))
        body.append(_factset([_fact("Action", durable.action), _fact("Owner", durable.owner)]))
        body.append(_text(durable.detail))
        if durable.command:
            body.append(_text(durable.command, fontType="Monospace", wrap=True))

    actions: list[dict] = []
    if pkg.trace_url:
        actions.append({"type": "Action.OpenUrl", "title": "Open trace", "url": pkg.trace_url})
    actions.append(
        {
            "type": "Action.Submit",
            "title": "Accept RCA",
            "data": {"incident_id": pkg.incident_id, "label": "accept"},
        }
    )
    actions.append(
        {
            "type": "Action.Submit",
            "title": "RCA is wrong",
            "data": {"incident_id": pkg.incident_id, "label": "wrong"},
        }
    )
    return _base_card(body, actions)


def build_delay_card(
    incident_id: str,
    service: str | None,
    severity: str,
    elapsed_s: float,
    stage_pending: str = "stage2",
    brand: str = "The Ark Enterprise",
) -> dict:
    """Sent by the watchdog when a stage is late so the on-call engineer knows the agent is still working."""
    label = "stage 2 (diagnosis)" if stage_pending == "stage2" else f"{stage_pending}"
    body = [
        _text(f"{brand} | OpsAgent Incident Bridge | delay notice", size="Small", isSubtle=True),
        _text(
            f"{(severity or 'info').upper()}: {service or 'unknown service'} - {label} still running",
            size="Large",
            weight="Bolder",
            color=_severity_colour(severity),
        ),
        _factset(
            [
                _fact("Incident", incident_id),
                _fact("Pending", label),
                _fact("Elapsed since alarm", _fmt_elapsed(elapsed_s)),
                _fact("Sent at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
            ]
        ),
        _text(
            "The diagnosis is taking longer than the target. Stage 1 facts still stand; the full root cause, "
            "code verdict and recommended fix will follow as soon as they are ready.",
        ),
    ]
    return _base_card(body, [])


def wrap_for_teams(card: dict) -> dict:
    """Envelope a Microsoft Teams incoming webhook expects."""
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


# --------------------------------------------------------------------------- renderings
def _iter_elements(elements: list[dict]):
    for el in elements:
        yield el
        for key in ("items", "columns"):
            nested = el.get(key)
            if isinstance(nested, list):
                yield from _iter_elements(nested)


def card_to_markdown(card: dict) -> str:
    """Readable Markdown rendering of the TextBlocks and FactSets (previews, Streamlit, the outbox)."""
    lines: list[str] = []
    for el in _iter_elements(card.get("body", [])):
        kind = el.get("type")
        if kind == "TextBlock":
            text = str(el.get("text", "")).rstrip()
            if not text:
                continue
            if el.get("fontType") == "Monospace":
                lines.extend(["```", text, "```", ""])
            elif el.get("size") == "Large":
                lines.extend([f"# {text}", ""])
            elif el.get("separator") and el.get("weight") == "Bolder":
                lines.extend([f"## {text}", ""])
            elif el.get("weight") == "Bolder":
                lines.extend([f"**{text}**", ""])
            elif el.get("isSubtle"):
                lines.extend([f"_{text}_", ""])
            else:
                lines.extend([text, ""])
        elif kind == "FactSet":
            for fact in el.get("facts", []):
                lines.append(f"- **{fact.get('title', '')}**: {fact.get('value', '')}")
            lines.append("")
    actions = card.get("actions") or []
    if actions:
        lines.append("Actions: " + ", ".join(str(a.get("title", a.get("type", ""))) for a in actions))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


_COLOUR_CSS = {"attention": "#b00020", "warning": "#b36b00", "accent": "#0b5cad", "good": "#1b7f3b", "default": "#1f1f1f"}


def card_to_html(card: dict) -> str:
    """Simple inline-styled HTML rendering of the same card (email bodies, the outbox, the Streamlit app)."""
    e = _html.escape
    parts: list[str] = [
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f1f1f;'
        'max-width:720px;margin:0 auto;padding:16px;border:1px solid #ddd;border-radius:8px">'
    ]
    for el in _iter_elements(card.get("body", [])):
        kind = el.get("type")
        if kind == "TextBlock":
            text = str(el.get("text", "")).rstrip()
            if not text:
                continue
            colour = _COLOUR_CSS.get(el.get("color", "default"), "#1f1f1f")
            if el.get("fontType") == "Monospace":
                parts.append(
                    '<pre style="background:#f4f4f4;border:1px solid #e1e1e1;border-radius:4px;padding:10px;'
                    f'font-family:Consolas,monospace;font-size:13px;white-space:pre-wrap">{e(text)}</pre>'
                )
            elif el.get("size") == "Large":
                parts.append(f'<h1 style="font-size:20px;margin:8px 0;color:{colour}">{e(text)}</h1>')
            elif el.get("separator") and el.get("weight") == "Bolder":
                parts.append(
                    f'<h2 style="font-size:16px;margin:18px 0 6px;padding-top:10px;border-top:1px solid #ddd;color:{colour}">'
                    f"{e(text)}</h2>"
                )
            elif el.get("weight") == "Bolder":
                parts.append(f'<p style="margin:6px 0;font-weight:bold;color:{colour}">{e(text)}</p>')
            elif el.get("isSubtle"):
                parts.append(f'<p style="margin:6px 0;color:#666;font-size:12px">{e(text)}</p>')
            else:
                parts.append(f'<p style="margin:6px 0;color:{colour}">{e(text)}</p>')
        elif kind == "FactSet":
            rows = "".join(
                '<tr><td style="padding:3px 12px 3px 0;font-weight:bold;vertical-align:top;white-space:nowrap">'
                f"{e(str(f.get('title', '')))}</td><td style=\"padding:3px 0;vertical-align:top\">{e(str(f.get('value', '')))}</td></tr>"
                for f in el.get("facts", [])
            )
            parts.append(f'<table style="border-collapse:collapse;margin:8px 0">{rows}</table>')
    actions = card.get("actions") or []
    if actions:
        buttons = []
        for a in actions:
            title = e(str(a.get("title", a.get("type", ""))))
            if a.get("type") == "Action.OpenUrl" and a.get("url"):
                buttons.append(
                    f'<a href="{e(str(a["url"]))}" style="display:inline-block;margin:4px 8px 4px 0;padding:6px 12px;'
                    f'background:#0b5cad;color:#fff;text-decoration:none;border-radius:4px">{title}</a>'
                )
            else:
                buttons.append(
                    '<span style="display:inline-block;margin:4px 8px 4px 0;padding:6px 12px;background:#eee;'
                    f'color:#333;border-radius:4px">{title}</span>'
                )
        parts.append('<div style="margin-top:12px">' + "".join(buttons) + "</div>")
    parts.append("</div>")
    return "\n".join(parts)
