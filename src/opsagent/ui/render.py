"""Pure rendering helpers for the run recorder UI. No Streamlit import here so everything is unit-testable.

Adaptive Card rendering covers the element types Incident Bridge emits: TextBlock, FactSet, Container, ColumnSet,
ActionSet (Action.OpenUrl) and Image (alt text only). Colours follow the restrained palette of the cards:
attention #C0392B, warning #B9770E, good #1E8449.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

COLOURS = {
    "attention": "#C0392B",
    "warning": "#B9770E",
    "good": "#1E8449",
    "accent": "#1F4E79",
    "dark": "#1B1B1B",
    "light": "#6B6B6B",
    "default": "#1B1B1B",
}
SIZES = {"small": "12px", "default": "14px", "medium": "16px", "large": "20px", "extralarge": "26px"}
WEIGHTS = {"bolder": "600", "lighter": "300", "default": "400"}
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

STATUS_WORDS = {"running": "running", "done": "done", "error": "error", "duplicate": "duplicate", "skipped": "skipped"}


# ---------------------------------------------------------------------------------------------------- formatting
def fmt_seconds(x: Any) -> str:
    """48.2 -> '48 s'; 245 -> '4 min 5 s'; 3725 -> '1 h 2 min'; None -> '–'."""
    if x is None or x == "":
        return "–"
    try:
        total = float(x)
    except (TypeError, ValueError):
        return str(x)
    if total < 0:
        total = 0.0
    secs = int(round(total))
    if secs < 60:
        return f"{secs} s"
    if secs < 3600:
        return f"{secs // 60} min {secs % 60} s"
    return f"{secs // 3600} h {(secs % 3600) // 60} min"


def fmt_cost(x: Any) -> str:
    """0.01234 -> '$0.0123'."""
    try:
        return f"${float(x or 0.0):.4f}"
    except (TypeError, ValueError):
        return "$0.0000"


def fmt_tokens(n: Any) -> str:
    try:
        return f"{int(n or 0):,}"
    except (TypeError, ValueError):
        return "0"


def parse_ts(value: Any) -> datetime | None:
    """ISO-8601 (with Z or offset) -> aware datetime; None if it cannot be parsed."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_local(value: Any, with_date: bool = True) -> str:
    """UTC ISO timestamp -> local wall-clock text such as '2026-11-15 16:22:07'."""
    dt = parse_ts(value)
    if dt is None:
        return "–"
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")


def run_label(run: dict) -> str:
    """Sidebar label: '<incident_id> · <status> · <started_at local time>'."""
    return f"{run.get('incident_id', '?')} · {run.get('status', '?')} · {fmt_local(run.get('started_at'))}"


def run_duration(run: dict) -> float | None:
    """Seconds from start to finish (or to now while running)."""
    if run.get("duration_s") is not None:
        return float(run["duration_s"])
    start = parse_ts(run.get("started_at"))
    if start is None:
        return None
    end = parse_ts(run.get("finished_at")) or datetime.now(timezone.utc)
    return max(0.0, (end - start).total_seconds())


# ---------------------------------------------------------------------------------------------------- steps
def steps_table(run: dict, now: datetime | None = None) -> list[dict]:
    """One row per step: name, kind, crew, start offset, duration, status, tokens, cost, error.
    Running steps get a live duration computed from their started_at."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    for step in run.get("steps", []) or []:
        usage = step.get("usage") or {}
        duration = step.get("duration_s")
        status = step.get("status") or "running"
        if duration is None:
            started = parse_ts(step.get("started_at"))
            if started is not None and status == "running":
                duration = round(max(0.0, (now - started).total_seconds()), 1)
        rows.append(
            {
                "step": step.get("name", "?"),
                "kind": step.get("kind") or "flow",
                "crew": step.get("crew") or "",
                "start_s": step.get("t_start") if step.get("t_start") is not None else 0.0,
                "duration_s": duration,
                "duration": fmt_seconds(duration) if duration is not None else "…",
                "status": status,
                "tokens": int(usage.get("total_tokens") or 0),
                "cost_usd": float(step.get("cost_usd") or 0.0),
                "error": step.get("error") or "",
            }
        )
    return rows


def timeline_html(run: dict, now: datetime | None = None) -> str:
    """Plotly-free horizontal bar timeline: one row per step, bar offset = t_start, width = duration.
    Running steps are drawn as a dashed outline so they stand out; errors carry a red label."""
    rows = steps_table(run, now=now)
    if not rows:
        return "<p class='oa-muted'>no steps recorded yet</p>"
    span = 0.0
    for r in rows:
        span = max(span, float(r["start_s"] or 0) + float(r["duration_s"] or 0))
    span = max(span, run_duration(run) or 0.0, 1.0)
    out = ["<div class='oa-timeline'>"]
    for r in rows:
        left = 100.0 * float(r["start_s"] or 0) / span
        width = max(0.6, 100.0 * float(r["duration_s"] or 0) / span)
        width = min(width, 100.0 - left)
        status = r["status"]
        cls = f"oa-bar oa-bar-{status}"
        label = html.escape(r["step"])
        crew = f" <span class='oa-muted'>{html.escape(r['crew'])}</span>" if r["crew"] else ""
        meta = r["duration"]
        if r["tokens"]:
            meta += f" · {fmt_tokens(r['tokens'])} tok · {fmt_cost(r['cost_usd'])}"
        if status == "running":
            meta += " · running"
        elif status == "error":
            meta += " · error"
        out.append(
            "<div class='oa-row'>"
            f"<div class='oa-step'><span class='oa-kind oa-kind-{html.escape(r['kind'])}'>{html.escape(r['kind'])}</span> "
            f"<strong>{label}</strong>{crew}</div>"
            f"<div class='oa-track'><div class='{cls}' style='left:{left:.2f}%;width:{width:.2f}%'></div></div>"
            f"<div class='oa-meta oa-meta-{status}'>{html.escape(meta)}</div>"
            "</div>"
        )
    out.append("</div>")
    return "".join(out)


def status_badge_html(status: str | None) -> str:
    status = (status or "unknown").lower()
    return f"<span class='oa-badge oa-badge-{html.escape(status)}'>{html.escape(status)}</span>"


def incident_headline(run: dict) -> str:
    """'CRITICAL · orders-api · process oom kill' from the triage artifact; '' before triage has run."""
    tri = (run.get("artifacts") or {}).get("triage") or {}
    cls = tri.get("classification") or {}
    parts = [str(tri.get("severity") or "").upper(), tri.get("service") or "",
             str(cls.get("sub_reason") or cls.get("reason") or "").replace("_", " ")]
    return " · ".join(p for p in parts if p)


def hero_html(run: dict, brand: str = "", is_sample: bool = False) -> str:
    """Dark header band: brand eyebrow, incident headline, id and status badges, run facts."""
    tri = (run.get("artifacts") or {}).get("triage") or {}
    inst = tri.get("instance") or {}
    severity = str(tri.get("severity") or "").lower()
    headline = incident_headline(run) or "Incident run"
    where = " · ".join(str(x) for x in (inst.get("instance_id"), inst.get("instance_type"), inst.get("region")) if x)
    eyebrow = " · ".join(x for x in (brand, "OpsAgent incident console") if x)
    badges = status_badge_html(run.get("status")) + (status_badge_html("sample") if is_sample else "")
    facts = [("model", run.get("model") or "–"), ("started", fmt_local(run.get("started_at"))),
             ("duration", fmt_seconds(run_duration(run))), ("event", run.get("event_id") or "–")]
    fact_html = "".join(f"<span><i>{html.escape(k)}</i>{html.escape(str(v))}</span>" for k, v in facts)
    return (
        f"<div class='oa-hero oa-hero-{html.escape(severity or 'none')}'>"
        f"<div class='oa-eyebrow'>{html.escape(eyebrow)}</div>"
        f"<div class='oa-hero-title'>{html.escape(headline)}</div>"
        f"<div class='oa-hero-id'><span class='oa-id'>{html.escape(str(run.get('incident_id', '?')))}</span>{badges}"
        f"<span class='oa-hero-where'>{html.escape(where)}</span></div>"
        f"<div class='oa-hero-facts'>{fact_html}</div>"
        "</div>"
    )


def kpi_html(run: dict, stage1_target_s: float | None = None) -> str:
    """Four headline numbers: time to first alert, time to root cause, LLM usage, cost."""
    timings = run.get("timings") or {}
    totals = run.get("totals") or {}
    s1 = timings.get("stage1")
    s1_note = "triage card sent to the on-call"
    if s1 is not None and stage1_target_s:
        s1_note = f"target under {int(stage1_target_s)} s · " + ("met" if float(s1) <= stage1_target_s else "missed")
    cards = [
        ("First alert", fmt_seconds(s1) if s1 is not None else "–", s1_note, "alert"),
        ("Root cause delivered", fmt_seconds(timings["stage2"]) if "stage2" in timings else "–",
         "diagnosis, code verdict and fixes", "rca"),
        ("LLM usage", fmt_tokens(totals.get("total_tokens")),
         f"tokens · {int(totals.get('llm_calls') or 0)} calls", "llm"),
        ("Cost per incident", f"${float(totals.get('cost_usd') or 0.0):.2f}", fmt_cost(totals.get("cost_usd")) + " USD", "cost"),
    ]
    out = ["<div class='oa-kpis'>"]
    for label, value, note, kind in cards:
        out.append(f"<div class='oa-kpi oa-kpi-{kind}'><div class='oa-kpi-label'>{html.escape(label)}</div>"
                   f"<div class='oa-kpi-value'>{html.escape(value)}</div>"
                   f"<div class='oa-kpi-note'>{html.escape(note)}</div></div>")
    out.append("</div>")
    return "".join(out)


def pipeline_html(run: dict, now: datetime | None = None) -> str:
    """One chip per crew in order of first appearance: status, time spent and tokens."""
    crews: dict[str, dict] = {}
    for r in steps_table(run, now=now):
        if not r["crew"]:
            continue
        c = crews.setdefault(r["crew"], {"duration": 0.0, "tokens": 0, "status": "done"})
        c["duration"] += float(r["duration_s"] or 0)
        c["tokens"] += r["tokens"]
        if r["status"] == "error" or (r["status"] == "running" and c["status"] != "error"):
            c["status"] = r["status"]
    if not crews:
        return ""
    chips = []
    for name, c in crews.items():
        meta = fmt_seconds(c["duration"]) + (f" · {fmt_tokens(c['tokens'])} tok" if c["tokens"] else "")
        chips.append(f"<div class='oa-crew oa-crew-{html.escape(c['status'])}'><span class='oa-dot'></span>"
                     f"<div><div class='oa-crew-name'>{html.escape(name)}</div>"
                     f"<div class='oa-crew-meta'>{html.escape(meta)}</div></div></div>")
    return "<div class='oa-pipeline'>" + "<span class='oa-arrow'>→</span>".join(chips) + "</div>"


# ---------------------------------------------------------------------------------------------------- Adaptive Cards
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _inline_md(text: str) -> str:
    """Adaptive Card TextBlocks allow a tiny markdown subset: **bold**, *italic*, [text](url), line breaks."""
    s = html.escape(str(text))
    s = _MD_BOLD.sub(r"<strong>\1</strong>", s)
    s = _MD_ITALIC.sub(r"<em>\1</em>", s)
    s = _MD_LINK.sub(r"<a href='\2' style='color:#1F4E79'>\1</a>", s)
    return s.replace("\n", "<br>")


def _text_block(el: dict) -> str:
    text = el.get("text", "")
    colour = COLOURS.get(str(el.get("color", "default")).lower(), COLOURS["default"])
    size = SIZES.get(str(el.get("size", "default")).lower(), SIZES["default"])
    weight = WEIGHTS.get(str(el.get("weight", "default")).lower(), WEIGHTS["default"])
    subtle = " opacity:0.72;" if el.get("isSubtle") else ""
    spacing = "margin:0 0 6px 0;"
    if str(el.get("fontType", "")).lower() == "monospace":
        body = html.escape(str(text))
        return (
            f"<pre style='{spacing} padding:8px 10px; background:#F6F6F6; border:1px solid #E3E3E3; border-radius:4px;"
            f" white-space:pre-wrap; word-break:break-word; font-size:12.5px; color:{colour};{subtle}'>"
            f"<code style='font-family:{MONO}'>{body}</code></pre>"
        )
    return (
        f"<p style='{spacing} font-size:{size}; font-weight:{weight}; color:{colour}; line-height:1.4;{subtle}'>"
        f"{_inline_md(text)}</p>"
    )


def _fact_set(el: dict) -> str:
    rows = []
    for fact in el.get("facts", []) or []:
        title = _inline_md(fact.get("title", ""))
        value = _inline_md(fact.get("value", ""))
        rows.append(
            "<tr>"
            f"<td style='padding:3px 14px 3px 0; color:#555; font-weight:600; white-space:nowrap; vertical-align:top'>{title}</td>"
            f"<td style='padding:3px 0; color:#1B1B1B; vertical-align:top'>{value}</td>"
            "</tr>"
        )
    return f"<table style='border-collapse:collapse; font-size:13.5px; margin:0 0 8px 0'>{''.join(rows)}</table>"


def _column_set(el: dict) -> str:
    cols = el.get("columns", []) or []
    parts = []
    for col in cols:
        width = col.get("width", "stretch")
        if width == "auto":
            flex = "flex:0 0 auto;"
        elif width == "stretch":
            flex = "flex:1 1 0;"
        else:
            try:
                flex = f"flex:{float(str(width).replace('px', ''))} 1 0;"
            except ValueError:
                flex = "flex:1 1 0;"
        parts.append(f"<div style='{flex} min-width:0; padding-right:14px'>{_items(col.get('items', []))}</div>")
    return f"<div style='display:flex; flex-wrap:wrap; gap:4px; margin:0 0 6px 0'>{''.join(parts)}</div>"


def _container(el: dict) -> str:
    style = str(el.get("style", "default")).lower()
    border = {
        "emphasis": "background:#F6F6F6; border:1px solid #E3E3E3;",
        "attention": f"border-left:3px solid {COLOURS['attention']};",
        "warning": f"border-left:3px solid {COLOURS['warning']};",
        "good": f"border-left:3px solid {COLOURS['good']};",
        "accent": f"border-left:3px solid {COLOURS['accent']};",
    }.get(style, "")
    pad = "padding:8px 12px;" if border else "padding:0;"
    return f"<div style='{border} {pad} margin:0 0 8px 0; border-radius:3px'>{_items(el.get('items', []))}</div>"


def _actions(actions: list[dict]) -> str:
    links = []
    for a in actions or []:
        title = html.escape(str(a.get("title", "Open")))
        url = a.get("url")
        if url:
            links.append(
                f"<a href='{html.escape(str(url))}' style='display:inline-block; padding:5px 12px; margin:0 8px 6px 0;"
                " border:1px solid #1F4E79; border-radius:4px; color:#1F4E79; text-decoration:none; font-size:13px'>"
                f"{title}</a>"
            )
        else:
            links.append(
                f"<span style='display:inline-block; padding:5px 12px; margin:0 8px 6px 0; border:1px solid #BBB;"
                f" border-radius:4px; color:#555; font-size:13px'>{title}</span>"
            )
    return f"<div style='margin:6px 0 0 0'>{''.join(links)}</div>" if links else ""


def _items(items: list[dict]) -> str:
    out = []
    for el in items or []:
        if not isinstance(el, dict):
            continue
        kind = str(el.get("type", "")).lower()
        if kind == "textblock":
            out.append(_text_block(el))
        elif kind == "factset":
            out.append(_fact_set(el))
        elif kind == "container":
            out.append(_container(el))
        elif kind == "columnset":
            out.append(_column_set(el))
        elif kind == "actionset":
            out.append(_actions(el.get("actions", [])))
        elif kind == "image":
            alt = el.get("altText") or el.get("url") or "image"
            out.append(f"<p style='color:#6B6B6B; font-size:12px'>[image: {html.escape(str(alt))}]</p>")
        elif kind == "richtextblock":
            text = "".join(str(r.get("text", "")) for r in el.get("inlines", []) if isinstance(r, dict))
            out.append(_text_block({"text": text}))
        elif "items" in el:
            out.append(_container(el))
    return "".join(out)


def card_html(card: dict) -> str:
    """Inline-styled HTML for an Adaptive Card dict (the `content` of a Teams message attachment, or the card itself)."""
    if not isinstance(card, dict):
        return "<p style='color:#6B6B6B'>no card</p>"
    # unwrap a Teams message payload or an attachment wrapper
    if "attachments" in card and isinstance(card["attachments"], list) and card["attachments"]:
        inner = card["attachments"][0]
        card = inner.get("content", inner) if isinstance(inner, dict) else card
    elif "content" in card and isinstance(card["content"], dict) and "body" in card["content"]:
        card = card["content"]
    body = _items(card.get("body", []))
    actions = _actions(card.get("actions", []))
    return (
        f"<div class='oa-card' style='font-family:{SANS}; color:#1B1B1B; background:#FFFFFF; border:1px solid #E3E3E3;"
        " border-radius:6px; padding:16px 18px; max-width:760px'>"
        f"{body}{actions}</div>"
    )


# ---------------------------------------------------------------------------------------------------- package -> card
def _fix_block(title: str, fix: dict | None) -> list[dict]:
    if not fix:
        return []
    items: list[dict] = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
        {"type": "TextBlock", "text": fix.get("detail", ""), "wrap": True},
    ]
    if fix.get("command"):
        items.append({"type": "TextBlock", "text": fix["command"], "fontType": "Monospace", "wrap": True})
    if fix.get("reversal"):
        items.append({"type": "TextBlock", "text": f"Reversal: {fix['reversal']}", "isSubtle": True, "wrap": True})
    return items


def package_card(pkg: dict) -> dict:
    """Build an Adaptive Card dict from an incident-package-1.0 dict, for runs whose outbox card is missing."""
    stage = pkg.get("stage", "stage1")
    severity = str(pkg.get("severity", "")).lower()
    colour = {"critical": "Attention", "warning": "Warning", "info": "Good"}.get(severity, "Default")
    triage = pkg.get("triage") or {}
    instance = triage.get("instance") or {}
    classification = triage.get("classification") or {}
    timings = pkg.get("timings") or {}
    facts = [
        {"title": "Incident", "value": pkg.get("incident_id", "")},
        {"title": "Severity", "value": severity or "–"},
        {"title": "Service", "value": pkg.get("service") or "–"},
        {"title": "Instance", "value": pkg.get("instance_id", "")
            + (f" ({instance['instance_type']})" if instance.get("instance_type") else "")},
        {"title": "Classification", "value": f"{classification.get('reason', '–')} / {classification.get('sub_reason', '–')}"
            + (f" ({classification['confidence']})" if classification.get("confidence") else "")},
    ]
    if triage.get("owner") or pkg.get("owner"):
        facts.append({"title": "Owner", "value": triage.get("owner") or pkg.get("owner")})
    for key in ("stage1", "stage2"):
        if key in timings:
            facts.append({"title": f"Time to {key.replace('stage', 'stage ')}", "value": fmt_seconds(timings[key])})
    body: list[dict] = [
        {"type": "TextBlock", "text": pkg.get("brand", "The Ark Enterprise") + " · OpsAgent", "isSubtle": True, "size": "Small"},
        {"type": "TextBlock", "text": pkg.get("headline", f"Incident {pkg.get('incident_id', '')}"),
         "weight": "Bolder", "size": "Large", "color": colour, "wrap": True},
        {"type": "TextBlock", "text": pkg.get("summary", ""), "wrap": True},
        {"type": "FactSet", "facts": facts},
    ]
    diagnosis = pkg.get("diagnosis") or {}
    if diagnosis.get("root_cause"):
        rc = diagnosis["root_cause"]
        body.append({"type": "Container", "style": "emphasis", "items": [
            {"type": "TextBlock", "text": "Root cause", "weight": "Bolder", "size": "Medium"},
            {"type": "TextBlock", "text": rc.get("summary", ""), "wrap": True},
            {"type": "FactSet", "facts": [
                {"title": "Category", "value": rc.get("category", "–")},
                {"title": "Confidence", "value": rc.get("confidence", "–")},
            ]},
        ]})
    cc = pkg.get("code_correlation") or {}
    if cc:
        loc = cc.get("locations") or []
        where = f"{loc[0].get('file')}:{loc[0].get('line')}" if loc else "–"
        body.append({"type": "FactSet", "facts": [
            {"title": "Code verdict", "value": f"{cc.get('verdict', '–')} ({float(cc.get('confidence', 0)):.0%})"},
            {"title": "Pattern", "value": cc.get("pattern", "–")},
            {"title": "Location", "value": where},
            {"title": "Developer action", "value": cc.get("developer_action", "–")},
        ]})
    body += _fix_block("Recommended fix (immediate)", pkg.get("recommended_fix"))
    body += _fix_block("Durable fix", pkg.get("durable_fix"))
    if stage == "stage1":
        body.append({"type": "TextBlock", "text": "Diagnosis and code correlation follow in stage 2.",
                     "isSubtle": True, "size": "Small"})
    actions = []
    if pkg.get("trace_url"):
        actions.append({"type": "Action.OpenUrl", "title": "Open trace", "url": pkg["trace_url"]})
    return {"type": "AdaptiveCard", "version": "1.5", "body": body, "actions": actions}
