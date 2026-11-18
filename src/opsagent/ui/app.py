"""OpsAgent run recorder: a Streamlit page over runs/<incident_id>/run.json and outbox/<incident_id>/*.

Start with `python -m streamlit run src/opsagent/ui/app.py` (or `python -m opsagent ui`). When the runs folder is
empty the page falls back to tests/fixtures/run_sample.json and says so."""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from opsagent.config import PROJECT_ROOT, get_settings
from opsagent.tracing import list_runs
from opsagent.ui import render as R

SETTINGS = get_settings()
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "run_sample.json"
SAMPLE_EVENT = PROJECT_ROOT / "events" / "log_event.json"
STYLE = Path(__file__).with_name("style.css")
REFRESH_SECONDS = 3
LABELS = ("accepted", "partially_correct", "wrong")

st.set_page_config(page_title="OpsAgent run recorder", layout="wide", initial_sidebar_state="expanded")
if STYLE.exists():
    st.markdown(f"<style>{STYLE.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------------------ data access
def load_runs() -> tuple[list[dict], bool]:
    """All recorded runs newest first; (fixture, True) when the runs folder has none."""
    runs = list_runs(SETTINGS.runs_path)
    if runs:
        return runs, False
    if FIXTURE.exists():
        try:
            return [json.loads(FIXTURE.read_text(encoding="utf-8"))], True
        except json.JSONDecodeError:
            return [], True
    return [], True


def outbox_file(incident_id: str, name: str) -> Path | None:
    p = SETTINGS.outbox_path / incident_id / name
    return p if p.exists() else None


def read_text(p: Path | None) -> str | None:
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ------------------------------------------------------------------------------------------------------ background run
def _bg_state() -> dict[str, Any]:
    return st.session_state.setdefault("bg", {"thread": None, "error": None, "result": None, "before": set(),
                                               "started": None})


def _run_sample_event(shared: dict[str, Any]) -> None:
    """Runs in a plain thread; never touches st.* here."""
    try:
        from opsagent.flow.incident_flow import run_event  # lazy: the module is being written in parallel

        shared["result"] = run_event(SAMPLE_EVENT, force=True)
    except Exception:  # noqa: BLE001
        shared["error"] = traceback.format_exc()


def start_sample_run(known_ids: set[str]) -> None:
    bg = _bg_state()
    if bg["thread"] is not None and bg["thread"].is_alive():
        return
    shared = {"result": None, "error": None}
    t = threading.Thread(target=_run_sample_event, args=(shared,), name="opsagent-sample-run", daemon=True)
    bg.update({"thread": t, "shared": shared, "error": None, "result": None, "before": set(known_ids),
               "started": time.time()})
    t.start()


def bg_running() -> bool:
    bg = _bg_state()
    t = bg.get("thread")
    return t is not None and t.is_alive()


def bg_collect() -> None:
    """Move the thread's outcome into session state once it is finished."""
    bg = _bg_state()
    shared = bg.get("shared") or {}
    if bg.get("thread") is not None and not bg_running():
        bg["error"] = shared.get("error")
        bg["result"] = shared.get("result")


# ------------------------------------------------------------------------------------------------------ small widgets
def kv(pairs: list[tuple[str, Any]]) -> None:
    rows = "".join(f"<div><span class='k'>{st_escape(k)}</span>{st_escape(v)}</div>" for k, v in pairs if v not in (None, ""))
    st.markdown(f"<div class='oa-kv'>{rows}</div>", unsafe_allow_html=True)


def st_escape(v: Any) -> str:
    import html

    if isinstance(v, bool):
        v = "yes" if v else "no"
    return html.escape(str(v))


def short_path(p: Path) -> str:
    """Project-relative when the path is inside the project, absolute otherwise."""
    try:
        return "./" + p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(p)


def table(rows: list[dict], columns: list[str] | None = None, empty: str = "none") -> None:
    if not rows:
        st.caption(empty)
        return
    if columns:
        rows = [{c: r.get(c) for c in columns} for r in rows]
    st.dataframe(rows, width="stretch", hide_index=True)


def raw_json(obj: Any, label: str = "Raw JSON") -> None:
    with st.expander(label):
        st.json(obj, expanded=False)


def not_yet(what: str) -> None:
    st.caption(f"{what}: not yet")


# ------------------------------------------------------------------------------------------------------ sidebar
runs, is_sample = load_runs()
ids = [r.get("incident_id", "?") for r in runs]
by_id = {r.get("incident_id", "?"): r for r in runs}

with st.sidebar:
    st.markdown(
        "<div class='oa-brand'><div class='oa-logo'>OA</div><div><div class='oa-brand-name'>OpsAgent</div>"
        f"<div class='oa-brand-sub'>{st_escape(SETTINGS.brand)} · run recorder</div></div></div>",
        unsafe_allow_html=True,
    )

    bg_collect()
    if bg_running():
        new_ids = [i for i in ids if i not in _bg_state()["before"]]
        if new_ids:
            st.session_state["selected_run"] = new_ids[0]
        with st.status("Running sample event…", state="running", expanded=True):
            elapsed = time.time() - (_bg_state()["started"] or time.time())
            st.write(f"elapsed {R.fmt_seconds(elapsed)}")
            st.write("new run detected" if new_ids else "waiting for runs/<incident_id>/run.json")
    else:
        bg = _bg_state()
        if bg.get("error"):
            st.error("Sample run failed")
            with st.expander("traceback"):
                st.code(bg["error"], language="text")
        elif bg.get("result") is not None and bg.get("thread") is not None:
            st.success("Sample run finished")
            with st.expander("result"):
                st.json(bg["result"], expanded=False)

    selected = st.session_state.get("selected_run")
    if selected not in by_id:
        selected = ids[0] if ids else None
        st.session_state["selected_run"] = selected
    if ids:
        choice = st.selectbox("Run", options=ids, index=ids.index(selected) if selected in ids else 0,
                              format_func=lambda i: R.run_label(by_id[i]))
        st.session_state["selected_run"] = choice
    else:
        st.info("No runs recorded yet.")

    c1, c2 = st.columns(2)
    if c1.button("Refresh", width="stretch"):
        st.rerun()
    if c2.button("Run sample event", width="stretch", disabled=bg_running()):
        start_sample_run(set(ids) if not is_sample else set())
        st.rerun()
    auto = st.toggle("Auto-refresh (3 s while a run is running)", value=st.session_state.get("auto_refresh", True),
                     key="auto_refresh")

    if is_sample:
        st.markdown(f"{R.status_badge_html('sample')} <span class='oa-muted'>sample run from "
                    f"<code>tests/fixtures/run_sample.json</code>; the runs folder is empty</span>",
                    unsafe_allow_html=True)
    st.markdown(f"<div class='oa-paths'>runs&nbsp;&nbsp;&nbsp;{st_escape(short_path(SETTINGS.runs_path))}<br>"
                f"outbox {st_escape(short_path(SETTINGS.outbox_path))}</div>", unsafe_allow_html=True)

run = by_id.get(st.session_state.get("selected_run")) if ids else None

# ------------------------------------------------------------------------------------------------------ main page
if run is None:
    st.markdown("## No run selected")
    st.write("Record a run with `python -m opsagent run` or press **Run sample event** in the sidebar.")
    st.stop()

incident_id = run.get("incident_id", "?")
status = run.get("status", "unknown")
artifacts = run.get("artifacts") or {}

st.markdown(R.hero_html(run, brand=SETTINGS.brand, is_sample=is_sample), unsafe_allow_html=True)
st.markdown(R.kpi_html(run, stage1_target_s=SETTINGS.stage1_target_seconds), unsafe_allow_html=True)

st.markdown("#### Agent crews")
st.markdown(R.pipeline_html(run), unsafe_allow_html=True)
st.markdown("#### Steps")
st.markdown(R.timeline_html(run), unsafe_allow_html=True)
with st.expander("Step table"):
    table(R.steps_table(run), ["step", "kind", "crew", "start_s", "duration", "status", "tokens", "cost_usd", "error"])

# ------------------------------------------------------------------------------------------------------ tabs
tabs = st.tabs(["Stage 1 card", "Stage 2 card", "Triage", "Diagnosis", "Code verdict", "Knowledge record",
                "Receipts", "Errors", "Raw run.json"])


def show_card(stage: str) -> None:
    """outbox HTML -> outbox card JSON -> package artifact -> 'not yet'."""
    html_text = read_text(outbox_file(incident_id, f"{stage}.card.html"))
    source = None
    if html_text:
        source = f"outbox/{incident_id}/{stage}.card.html"
    else:
        card_json = read_text(outbox_file(incident_id, f"{stage}.card.json"))
        if card_json:
            try:
                html_text = R.card_html(json.loads(card_json))
                source = f"outbox/{incident_id}/{stage}.card.json"
            except json.JSONDecodeError as exc:
                st.warning(f"{stage}.card.json is not valid JSON: {exc}")
        if html_text is None and artifacts.get(f"package_{stage}"):
            html_text = R.card_html(R.package_card(artifacts[f"package_{stage}"]))
            source = f"artifact package_{stage} (rendered by the UI)"
    if html_text is None:
        not_yet(f"{stage} card")
        return
    st.caption(f"source: {source}")
    components.html(html_text, height=min(1400, 260 + html_text.count("<p") * 26 + html_text.count("<tr") * 22),
                    scrolling=True)
    md = read_text(outbox_file(incident_id, f"{stage}.card.md"))
    if md:
        with st.expander("Markdown version"):
            st.markdown(md)
    email = read_text(outbox_file(incident_id, f"{stage}.email.html"))
    if email:
        with st.expander("Email version"):
            components.html(email, height=700, scrolling=True)
    card_json = read_text(outbox_file(incident_id, f"{stage}.card.json"))
    if card_json:
        with st.expander("Card JSON"):
            st.code(card_json, language="json")
    if artifacts.get(f"package_{stage}"):
        raw_json(artifacts[f"package_{stage}"], f"Raw package_{stage}")


with tabs[0]:
    show_card("stage1")
with tabs[1]:
    show_card("stage2")

with tabs[2]:
    tri = artifacts.get("triage")
    if not tri:
        not_yet("triage")
    else:
        cls = tri.get("classification") or {}
        inst = tri.get("instance") or {}
        ev = tri.get("evidence") or {}
        a, b, c = st.columns(3)
        with a:
            st.markdown("**Classification**")
            kv([("severity", tri.get("severity")), ("reason", cls.get("reason")), ("sub reason", cls.get("sub_reason")),
                ("confidence", cls.get("confidence")), ("rule", cls.get("rule"))])
        with b:
            st.markdown("**Instance**")
            kv([("instance", inst.get("instance_id")), ("type", inst.get("instance_type")),
                ("memory", f"{inst['total_memory_mb']} MB" if inst.get("total_memory_mb") else None),
                ("region", inst.get("region")), ("service", tri.get("service")), ("owner", tri.get("owner")),
                ("source", inst.get("source"))])
        with c:
            st.markdown("**Alarm**")
            al = tri.get("alarm") or {}
            kv([("name", al.get("name")), ("state", al.get("state")), ("fired", R.fmt_local(al.get("fired_at"))),
                ("window", f"{R.fmt_local((tri.get('window') or {}).get('start'), False)} – "
                           f"{R.fmt_local((tri.get('window') or {}).get('end'), False)}")])
        if tri.get("summary"):
            st.markdown(f"**Summary** {st_escape(tri['summary'])}")
        if tri.get("analyst_agrees") is not None:
            note = f" · {tri['analyst_note']}" if tri.get("analyst_note") else ""
            st.markdown(f"<div class='oa-note'>analyst {'agrees' if tri['analyst_agrees'] else 'disagrees'} with the rule"
                        f"{st_escape(note)} · rationale: {st_escape(cls.get('rationale', ''))}</div>", unsafe_allow_html=True)
        st.markdown("**Evidence**")
        lp = ev.get("leak_profile")
        if lp:
            kv([("leak", f"{lp.get('slope_mb_per_min', 0):.0f} MB/min, {lp.get('first_rss_mb')} → {lp.get('peak_rss_mb')} MB "
                         f"over {lp.get('samples')} samples"),
                ("available at kill", f"{lp.get('mem_available_pct_at_kill')} %"), ("restarts", ev.get("restart_count"))])
        e1, e2 = st.columns(2)
        with e1:
            st.caption("OOM events")
            table([{"time": R.fmt_local(o.get("timestamp"), False), "process": o.get("killed_process"), "pid": o.get("killed_pid"),
                    "anon RSS MB": round((o.get("anon_rss_kb") or 0) / 1024), "cgroup": o.get("cgroup")}
                   for o in ev.get("oom_events") or []])
        with e2:
            st.caption("Service events")
            table([{"time": R.fmt_local(s.get("timestamp"), False), "unit": s.get("unit"), "event": s.get("event"),
                    "detail": s.get("detail")} for s in ev.get("service_events") or []])
        if ev.get("top_errors"):
            st.caption("Top log messages")
            table(ev["top_errors"], ["level", "message", "count", "last_seen"])
        for n in ev.get("notes") or []:
            st.caption(f"note: {n}")
        raw_json(tri, "Raw triage")

with tabs[3]:
    dg = artifacts.get("diagnosis")
    if not dg:
        not_yet("diagnosis")
    else:
        rc = dg.get("root_cause") or {}
        a, b = st.columns([3, 1])
        with a:
            st.markdown("**Root cause**")
            st.write(rc.get("summary", ""))
            for item in rc.get("contributing") or []:
                st.markdown(f"- {item}")
        with b:
            kv([("category", rc.get("category")), ("confidence", rc.get("confidence")),
                ("classification", dg.get("classification_agreement")), ("severity", dg.get("severity"))])
        if dg.get("notes"):
            st.markdown(f"<div class='oa-note'>{st_escape(dg['notes'])}</div>", unsafe_allow_html=True)
        st.markdown("**Fixes**")
        table([{"horizon": f.get("horizon"), "owner": f.get("owner"), "action": f.get("action"), "detail": f.get("detail"),
                "command": f.get("command") or "", "reversal": f.get("reversal") or ""} for f in dg.get("fixes") or []])
        for f in dg.get("fixes") or []:
            if f.get("command") and f["command"].strip().upper() != "N/A":
                st.code(f["command"], language="bash")
        st.markdown("**Citations**")
        table(dg.get("citations") or [], ["title", "source", "snippet"])
        st.markdown("**Timeline**")
        table(dg.get("timeline") or [], ["ts", "source", "what"])
        raw_json(dg, "Raw diagnosis")

with tabs[4]:
    cc = artifacts.get("code_correlation")
    if not cc:
        not_yet("code verdict")
    else:
        a, b, c, d = st.columns(4)
        a.markdown(f"<div class='oa-muted'>verdict</div><div class='oa-verdict'>{st_escape(cc.get('verdict', '–'))}</div>",
                   unsafe_allow_html=True)
        try:
            conf = f"{float(cc.get('confidence', 0)):.0%}"
        except (TypeError, ValueError):
            conf = str(cc.get("confidence"))
        b.markdown(f"<div class='oa-muted'>confidence</div><div class='oa-verdict'>{conf}</div>", unsafe_allow_html=True)
        c.markdown(f"<div class='oa-muted'>pattern</div><div class='oa-verdict' style='font-size:20px'>"
                   f"{st_escape(cc.get('pattern', '–'))}</div>", unsafe_allow_html=True)
        d.markdown(f"<div class='oa-muted'>repository</div><div class='oa-mono'>{st_escape(cc.get('repository') or '–')}</div>",
                   unsafe_allow_html=True)
        if cc.get("explanation"):
            st.write(cc["explanation"])
        st.markdown("**Developer action**")
        st.info(cc.get("developer_action") or "–")
        st.markdown("**Locations**")
        locs = cc.get("locations") or []
        table([{"file": l.get("file"), "symbol": l.get("symbol"), "line": l.get("line"), "why": l.get("why")} for l in locs])
        for l in locs:
            if l.get("excerpt"):
                st.caption(f"{l.get('file')}:{l.get('line')} {l.get('symbol') or ''}")
                st.code(l["excerpt"], language="python")
        if cc.get("recent_commits"):
            st.markdown("**Recent commits**")
            table([{"sha": c_.get("sha"), "date": c_.get("date"), "message": c_.get("message"),
                    "files": ", ".join(c_.get("files") or [])} for c_ in cc["recent_commits"]])
        raw_json(cc, "Raw code_correlation")

with tabs[5]:
    kb = artifacts.get("kb_record")
    if not kb:
        not_yet("knowledge record")
    else:
        a, b = st.columns([2, 1])
        with a:
            kv([("digest", kb.get("digest")), ("root cause", kb.get("root_cause_summary")),
                ("category", kb.get("root_cause_category")), ("verdict", kb.get("verdict")),
                ("code location", kb.get("code_location")), ("immediate fix", kb.get("immediate_fix")),
                ("durable fix", kb.get("durable_fix")), ("outcome", kb.get("outcome"))])
        with b:
            kv([("label", kb.get("label")), ("labelled by", kb.get("labelled_by")),
                ("labelled at", R.fmt_local(kb.get("labelled_at")) if kb.get("labelled_at") else None),
                ("tags", ", ".join(kb.get("tags") or [])), ("created", R.fmt_local(kb.get("created_at")))])
        if kb.get("citations"):
            st.caption("Citations")
            for c_ in kb["citations"]:
                st.markdown(f"- `{c_}`")
        raw_json(kb, "Raw kb_record")

with tabs[6]:
    receipts = run.get("receipts") or []
    table([{"channel": r.get("channel"), "stage": r.get("stage"), "ok": bool(r.get("ok")), "detail": r.get("detail"),
            "target": r.get("target"), "sent": R.fmt_local(r.get("sent_at"), False)} for r in receipts],
          empty="no receipts yet")

with tabs[7]:
    errors = run.get("errors") or []
    if not errors:
        st.caption("no errors")
    else:
        for e in errors:
            if isinstance(e, dict):
                st.error(f"{e.get('step', '?')} · {R.fmt_local(e.get('at'))}")
                st.code(str(e.get("error", "")), language="text")
            else:
                st.error(str(e))

with tabs[8]:
    st.json(run, expanded=False)
    st.download_button("Download run.json", json.dumps(run, indent=2, ensure_ascii=False, default=str),
                       file_name=f"{incident_id}.run.json", mime="application/json")

# ------------------------------------------------------------------------------------------------------ labelling
st.markdown("#### Label this RCA")
has_kb = bool(artifacts.get("kb_record"))
l1, l2, l3 = st.columns([2, 1, 1])
label = l1.radio("Label", LABELS, horizontal=True, disabled=not has_kb,
                 help="accepted: root cause and fixes were right · partially_correct: cause right, fix wrong or incomplete"
                      " · wrong: cause wrong")
by = l2.text_input("Labelled by", value="l2-oncall", disabled=not has_kb)
if l3.button("Save label", disabled=not has_kb or is_sample, width="stretch"):
    try:
        from opsagent.kb.incidents import label_incident  # lazy: module written in parallel

        rec = label_incident(incident_id, label, by)
        rec_json = json.loads(rec.model_dump_json()) if hasattr(rec, "model_dump_json") else rec
        st.success(f"{incident_id} labelled {label} by {by}")
        st.json(rec_json, expanded=False)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Labelling failed: {exc}")
        with st.expander("traceback"):
            st.code(traceback.format_exc(), language="text")
if not has_kb:
    st.caption("Labelling is enabled once the Knowledge crew has written artifacts.kb_record.")
elif is_sample:
    st.caption("Sample run: labels are not saved.")

# ------------------------------------------------------------------------------------------------------ auto refresh
if st.session_state.get("auto_refresh", True):
    anything_running = status == "running" or bg_running() or any(r.get("status") == "running" for r in runs)
    if anything_running:
        time.sleep(REFRESH_SECONDS)
        st.rerun()
