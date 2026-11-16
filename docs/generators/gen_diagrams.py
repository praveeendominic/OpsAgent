"""Generate OpsAgent architecture deliverables: a 4-page draw.io file and two standalone SVGs."""
import html, sys, os, datetime

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
E = lambda s: html.escape(s, quote=True)
FONT = "fontFamily=Helvetica;"
SVGFONT = "Segoe UI, Helvetica, Arial, sans-serif"
INK, QUIET = "#1F2933", "#5F6B7A"


# ---------- draw.io page builder ----------
class Page:
    def __init__(self, pid, name, w, h):
        self.id, self.name, self.w, self.h, self.cells, self.n = pid, name, w, h, [], 1

    def nid(self):
        self.n += 1
        return f"{self.id}-{self.n}"

    def vertex(self, label, x, y, w, h, style, parent="1", cid=None):
        cid = cid or self.nid()
        self.cells.append(
            f'<mxCell id="{cid}" value="{E(label)}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def edge(self, src, tgt, label="", style="", points=None, sp=None, tp=None, parent="1"):
        cid = self.nid()
        geo = '<mxGeometry relative="1" as="geometry">'
        if sp:
            geo += f'<mxPoint x="{sp[0]}" y="{sp[1]}" as="sourcePoint"/>'
        if tp:
            geo += f'<mxPoint x="{tp[0]}" y="{tp[1]}" as="targetPoint"/>'
        if points:
            geo += '<Array as="points">' + ''.join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + '</Array>'
        geo += '</mxGeometry>'
        s = f' source="{src}"' if src else ''
        t = f' target="{tgt}"' if tgt else ''
        self.cells.append(f'<mxCell id="{cid}" value="{E(label)}" style="{style}" edge="1" parent="{parent}"{s}{t}>{geo}</mxCell>')
        return cid

    def xml(self):
        return (f'<diagram id="{self.id}" name="{E(self.name)}"><mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" '
                f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.w}" '
                f'pageHeight="{self.h}" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                + ''.join(self.cells) + '</root></mxGraphModel></diagram>')


def box_style(fill, stroke, width=1.5, font=INK):
    return (f"rounded=1;whiteSpace=wrap;html=1;arcSize=14;fillColor={fill};strokeColor={stroke};fontColor={font};"
            f"strokeWidth={width};fontSize=12;align=center;verticalAlign=middle;spacing=4;" + FONT)


def lane_style(fill, stroke, font):
    return (f"swimlane;rounded=1;arcSize=5;startSize=32;html=1;fontStyle=1;fontSize=13;fillColor={fill};strokeColor={stroke};"
            f"fontColor={font};swimlaneFillColor=#FFFFFF;strokeWidth=1.5;align=left;spacingLeft=12;collapsible=0;" + FONT)


def text_style(size=18, bold=True, align="left", color=INK):
    return f"text;html=1;fontSize={size};fontStyle={1 if bold else 0};align={align};verticalAlign=middle;fontColor={color};" + FONT


EDGE_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#5F6B7A;strokeWidth=1.5;"
              "fontSize=11;fontColor=#5F6B7A;labelBackgroundColor=#FFFFFF;" + FONT)


def lbl(name, body):
    return f'<b>{name}</b><br><font color="{QUIET}">{body}</font>'


# ---------- shared data: architecture ----------
PAL = {
    "signals": ("#ECEFF1", "#607D8B", "#263238"),
    "ingest": ("#E3F2FD", "#1E88E5", "#0D47A1"),
    "flow": ("#E8F5E9", "#43A047", "#1B5E20"),
    "actions": ("#F3E5F5", "#8E24AA", "#4A148C"),
    "foundation": ("#FFF8E1", "#FFB300", "#E65100"),
}
ACCENT_FILL, ACCENT_STROKE = "#FFF3E0", "#FB8C00"
ARCH = [
    ("signals", "EVENT CAPTURE  ·  native AWS signals, plus the OpsAgent enricher", [[
        ("EC2 instance", "CloudWatch agent"), ("CloudWatch", "metrics and logs"), ("Alarm", "EventBridge rule"),
        ("Lambda enricher", "15 min evidence window")]]),
    ("ingest", "INGESTION  ·  durable hand-off into the Flow", [[
        ("SQS FIFO queue", "dedupe on event_id"), ("Flow intake", "validate, parse, classify"),
        ("Flow state", "Postgres, resumable"), ("Watchdog", "delay notice at 5 min")]]),
    ("flow", "CREWAI INCIDENTFLOW  ·  one persisted state, six crews", [
        [("Triage", "Parse, classify by rule, severity<br>writes triage-1.0"),
         ("Diagnostics", "RCA with citations from KB<br>ranks immediate, durable fixes"),
         ("Code Correlation", "Repo path behind the log line<br>verdict: code, infra, shared")],
        [("Incident Bridge", "Stage 1 at T+60 s, stage 2 RCA<br>Teams, email, xMatters"),
         ("Self-Healing", "Catalog action, dry-run<br>approve, verify, roll back"),
         ("Knowledge", "Docs refresh on cadence<br>incident write-back, label")]]),
    ("actions", "ACTIONS AND NOTIFICATIONS", [[
        ("Teams", "adaptive card"), ("Email", "SMTP relay"), ("xMatters", "voice page"),
        ("SSM + boto3", "approved only"), ("Terraform PR", "durable change")]]),
    ("foundation", "FOUNDATION  ·  read-only tools, model and tracing used by every crew", [[
        ("Vector store", "Chroma, pgvector"), ("AWS Docs MCP", "live documentation"), ("GitHub MCP", "read-only repo"),
        ("Azure OpenAI", "gpt-4o"), ("Langfuse", "traces, cost")]]),
]
ACCENT = {"Self-Healing", "SSM + boto3"}
ARCH_EDGES = ["raw-1.0 event", "kickoff_async(event)", "notify;  remediate only after approval", None, None]
TITLE = "OpsAgent: one Flow, six crews, from alarm to an approved fix in under five minutes"
SUBTITLE = "Orange outline = the only components that can change infrastructure, used after a human approval. Only the CloudWatch agent, metrics, logs and alarms exist today; everything from the enricher down is proposed."


def arch_layout(left=30, top=70, width=1100, pad=20, gap=20, vgap=40):
    """Return band rectangles and box rectangles in absolute coordinates."""
    out, y = [], top
    for key, title, rows in ARCH:
        inner = width - 2 * pad
        two = any("<br>" in b for r in rows for _, b in r)
        bh = 86 if two else 64
        h = 32 + 13 + len(rows) * bh + (len(rows) - 1) * 16 + 16
        boxes = []
        for ri, row in enumerate(rows):
            n = len(row)
            bw = (inner - (n - 1) * gap) / n
            for ci, (name, body) in enumerate(row):
                bx = left + pad + ci * (bw + gap)
                by = y + 45 + ri * (bh + 16)
                boxes.append((name, body, bx, by, bw, bh))
        out.append(dict(key=key, title=title, x=left, y=y, w=width, h=h, boxes=boxes))
        y += h + vgap
    return out, y - vgap


# ---------- page 1: architecture ----------
def page_arch():
    bands, bottom = arch_layout()
    p = Page("arch", "1. Architecture (AWS PoC)", 1169, int(bottom + 60))
    p.vertex(TITLE, 30, 18, 1100, 32, text_style(18))
    p.vertex(f'<font color="{QUIET}">{SUBTITLE}</font>', 30, 46, 1100, 20, text_style(11, False))
    ids = []
    for b in bands:
        fill, stroke, font = PAL[b["key"]]
        lid = p.vertex(b["title"], b["x"], b["y"], b["w"], b["h"], lane_style(fill, stroke, font))
        ids.append(lid)
        for name, body, bx, by, bw, bh in b["boxes"]:
            acc = name in ACCENT
            st = box_style(ACCENT_FILL if acc else "#FFFFFF", ACCENT_STROKE if acc else stroke, 2.5 if acc else 1.5)
            p.vertex(lbl(name, body), round(bx - b["x"], 1), by - b["y"], round(bw, 1), bh, st, parent=lid)
    for i, label in enumerate(ARCH_EDGES):
        if label is None:
            continue
        p.edge(ids[i], ids[i + 1], label,
               EDGE_STYLE + "exitX=0.5;exitY=1;entryX=0.5;entryY=0;verticalAlign=middle;align=left;spacingLeft=8;")
    return p


# ---------- page 2: flow graph ----------
FLOW_NODES = {  # key: (col, row, name, sub, kind)   kind: box | dia | dashed | accent | adia
    "intake": (1, 0, "intake  @start", "raw-1.0 or classified-1.0", "box"),
    "watchdog": (2, 1, "watchdog", "delay notice at T+5 min", "dashed"),
    "triage": (1, 1, "triage", "Triage crew  →  triage-1.0", "box"),
    "router": (1, 2, "@router  severity?", "", "dia"),
    "low": (0, 2, "log or warn", "info logs, warning notes", "box"),
    "page1": (0, 3, "page_stage1", "Incident Bridge, T+60 s", "box"),
    "diagnose": (1, 3, "diagnose", "Diagnostics crew", "box"),
    "correlate": (2, 3, "correlate_code", "Code Correlation crew", "box"),
    "plan": (0, 4, "plan_remediation", "Self-Healing planner", "accent"),
    "page2": (1, 4, "page_stage2", "Incident Bridge, full RCA", "box"),
    "gate": (0, 5, "approved?", "", "adia"),
    "execute": (0, 6, "execute_remediation", "SSM, boto3, verify, roll back", "accent"),
    "close": (1, 6, "close", "Knowledge crew  →  kb-record-1.0", "box"),
}
COLS, ROWS, FW, FH = [225, 570, 915], [100, 205, 325, 460, 595, 730, 865], 270, 72


def page_flow():
    p = Page("flow", "2. CrewAI IncidentFlow", 1169, 980)
    p.vertex("IncidentFlow: critical events fan out to three crews; only remediation waits for a person",
             30, 18, 1100, 32, text_style(18))
    ids = {}
    green = PAL["flow"][1]
    for k, (c, r, name, sub, kind) in FLOW_NODES.items():
        cx, cy = COLS[c], ROWS[r]
        if kind in ("dia", "adia"):
            acc = kind == "adia"
            st = (f"rhombus;whiteSpace=wrap;html=1;fillColor={ACCENT_FILL if acc else '#FFFFFF'};"
                  f"strokeColor={ACCENT_STROKE if acc else green};strokeWidth={2.5 if acc else 1.5};"
                  f"fontSize=12;fontStyle=1;fontColor={INK};" + FONT)
            ids[k] = p.vertex(name, cx - 105, cy - 42, 210, 84, st)
        else:
            acc = kind == "accent"
            st = box_style(ACCENT_FILL if acc else "#FFFFFF", ACCENT_STROKE if acc else green, 2.5 if acc else 1.5)
            if kind == "dashed":
                st += "dashed=1;dashPattern=6 4;"
            ids[k] = p.vertex(lbl(name, sub) if sub else f"<b>{name}</b>", cx - FW / 2, cy - FH / 2, FW, FH, st)

    def e(a, b, label="", extra="", pts=None):
        p.edge(ids[a], ids[b], label, EDGE_STYLE + extra, pts)

    e("intake", "triage")
    e("triage", "router")
    e("router", "low", "info, warning", "exitX=0;exitY=0.5;entryX=1;entryY=0.5;verticalAlign=bottom;")
    e("router", "diagnose", "critical", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;align=left;spacingLeft=8;")
    e("router", "page1", "", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(570, 395), (225, 395)])
    e("router", "correlate", "", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(570, 395), (915, 395)])
    e("diagnose", "page2", "", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
    e("diagnose", "plan", "", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;", [(570, 525), (225, 525)])
    e("correlate", "page2", "and_(diagnose, correlate_code)",
      "exitX=0.5;exitY=1;entryX=0.75;entryY=0;verticalAlign=bottom;", [(915, 540), (637, 540)])
    e("plan", "gate")
    e("gate", "execute", "yes", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;align=left;spacingLeft=8;")
    e("gate", "close", "declined or expired", "exitX=1;exitY=0.5;entryX=0.2;entryY=0;verticalAlign=bottom;", [(489, 730)])
    e("page2", "close", "", "exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
    e("execute", "close", "", "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
    e("intake", "watchdog", "timer from intake", "dashed=1;exitX=1;exitY=0.5;entryX=0.5;entryY=0;verticalAlign=bottom;", [(915, 100)])
    p.vertex(f'<font color="{QUIET}">Orange = Self-Healing, the only steps with write access. '
             f'The approval diamond is where the Flow pauses with its state persisted.</font>',
             30, 920, 1100, 20, text_style(11, False))
    return p


# ---------- shared data: sequence ----------
PARTS = [("CW", "CloudWatch +<br>EventBridge"), ("DL", "Lambda<br>enricher"), ("Q", "SQS FIFO"),
         ("T", "Triage crew"), ("F", "IncidentFlow"), ("D", "Diagnostics<br>crew"), ("C", "Code Correlation<br>crew"),
         ("IB", "Incident Bridge"), ("L2", "L2 on-call<br>(Teams, xMatters)"), ("SH", "Self-Healing<br>crew"),
         ("K", "Knowledge crew")]
MSGS = [  # (y, from, to, label, return?)  |  ("par", y1, y2)  |  ("sep", y, text)
    (130, "CW", "DL", "ALARM state change  (T+0)", False),
    (170, "DL", "Q", "raw-1.0 event  (T+15 s)", False),
    (210, "Q", "F", "kickoff_async(event)", False),
    (250, "F", "T", "triage", False),
    (290, "T", "F", "triage-1.0, severity critical  (T+45 s)", True),
    ("par", 315, 600),
    (350, "F", "IB", "page_stage1", False),
    (390, "IB", "L2", "Teams card, email, xMatters page  (T+60 s)", False),
    ("sep", 415, "and  diagnose"),
    (445, "F", "D", "diagnose", False),
    (485, "D", "F", "diagnosis-1.0 with citations  (T+3 min)", True),
    ("sep", 510, "and  correlate code"),
    (540, "F", "C", "correlate_code", False),
    (580, "C", "F", "code-correlation-1.0, verdict shared  (T+3.5 min)", True),
    (630, "F", "SH", "plan_remediation  (listens on diagnose)", False),
    (670, "SH", "F", "remediation-plan-1.0 with dry-run", True),
    (710, "F", "IB", "page_stage2  (and_ join)", False),
    (750, "IB", "L2", "card updated: RCA, verdict, fix, Approve  (T+4 min)", False),
    (790, "L2", "F", "Approve  (signed link or xMatters response)", True),
    (830, "F", "SH", "execute_remediation", False),
    (870, "SH", "F", "remediation-result-1.0, service healthy", True),
    (910, "F", "IB", "closure update", False),
    (950, "F", "K", "close", False),
    (990, "K", "F", "kb-record-1.0 stored with human label", True),
]
SEQ_X0, SEQ_SP, SEQ_LW, SEQ_TOP, SEQ_H = 40, 150, 120, 60, 1000
PX = {k: SEQ_X0 + i * SEQ_SP + SEQ_LW / 2 for i, (k, _) in enumerate(PARTS)}
PART_COLOR = {"CW": "signals", "DL": "signals", "Q": "ingest", "T": "flow", "F": "ingest", "D": "flow", "C": "flow",
              "IB": "flow", "L2": "actions", "SH": "flow", "K": "flow"}
PAR_X1 = SEQ_X0 + 3 * SEQ_SP + 20
PAR_X2 = SEQ_X0 + 10 * SEQ_SP - 20 + SEQ_LW


def page_seq():
    p = Page("seq", "3. Sequence: alarm to knowledge write-back", 1720, 1120)
    p.vertex("Sequence: alarm to approved fix to knowledge write-back (target times for the demo OOM)",
             30, 14, 1400, 32, text_style(18))
    for m in MSGS:  # par frame first so it sits behind
        if m[0] == "par":
            p.vertex("par", PAR_X1, m[1], PAR_X2 - PAR_X1, m[2] - m[1],
                     "shape=umlFrame;whiteSpace=wrap;html=1;width=50;height=22;fontSize=11;fontStyle=1;"
                     "strokeColor=#90A4AE;fontColor=#455A64;fillColor=none;" + FONT)
    ids = {}
    for k, name in PARTS:
        fill, stroke, font = PAL[PART_COLOR[k]]
        acc = k == "SH"
        st = (f"shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=1;dropTarget=0;"
              f"collapsible=0;recursiveResize=0;outlineConnect=0;portConstraint=eastwest;size=50;rounded=1;arcSize=20;"
              f"fontSize=12;fontStyle=1;fillColor={ACCENT_FILL if acc else fill};"
              f"strokeColor={ACCENT_STROKE if acc else stroke};fontColor={font};strokeWidth=1.5;" + FONT)
        ids[k] = p.vertex(name, PX[k] - SEQ_LW / 2, SEQ_TOP, SEQ_LW, SEQ_H, st)
    for m in MSGS:
        if m[0] == "par":
            continue
        if m[0] == "sep":
            y, text = m[1], m[2]
            p.edge(None, None, "", "endArrow=none;dashed=1;strokeColor=#90A4AE;html=1;", sp=(PAR_X1, y), tp=(PAR_X2, y))
            p.vertex(text, PAR_X1 + 6, y - 2, 160, 18, text_style(10.5, True, "left", "#455A64"))
            continue
        y, a, b, label, ret = m
        st = ("html=1;verticalAlign=bottom;endArrow=block;endFill=1;strokeColor=#5F6B7A;strokeWidth=1.5;fontSize=11;"
              "fontColor=#1F2933;labelBackgroundColor=#FFFFFF;" + FONT)
        if ret:
            st = st.replace("endArrow=block;endFill=1;", "endArrow=open;endFill=0;dashed=1;")
        p.edge(ids[a], ids[b], label, st, sp=(PX[a], y), tp=(PX[b], y))
    return p


# ---------- page 4: OpenStack mapping ----------
MAP = [  # (function, aws, openstack, adapter)
    ("Metrics", "CloudWatch agent, mem_used_percent", "Prometheus node_exporter, or Ceilometer + Gnocchi", "SignalSource"),
    ("Alarm", "CloudWatch alarm", "Alertmanager rule, or Aodh alarm", "SignalSource"),
    ("Logs", "CloudWatch Logs", "Loki + Promtail, or Elasticsearch + Fluent Bit", "SignalSource"),
    ("Trigger and collect", "EventBridge + Lambda enricher", "Alertmanager webhook + FastAPI collector", "SignalSource"),
    ("Queue", "SQS FIFO", "RabbitMQ quorum queue, or Redis Streams", "Listener"),
    ("Describe and resize", "DescribeInstances, stop, modify type, start", "openstacksdk get_server, resize_server, confirm", "InstanceAPI"),
    ("Scale out", "Auto Scaling group desired capacity", "Senlin scale-out, or Heat AutoScalingGroup", "InstanceAPI"),
    ("Run command on host", "SSM Run Command", "Ansible over SSH via bastion, key in Vault", "HostExec"),
    ("Secrets", "Secrets Manager", "Barbican, or HashiCorp Vault", "Config"),
    ("Audit", "CloudTrail", "Keystone + Nova CADF audit middleware", "Config"),
    ("Durable IaC", "Terraform AWS provider PR", "Terraform OpenStack provider, or Heat PR", "Self-Healing"),
]
ADAPTER_COLOR = {"SignalSource": "ingest", "Listener": "signals", "InstanceAPI": "flow", "HostExec": "actions",
                 "Config": "foundation", "Self-Healing": "flow"}


def page_map():
    rh, gap, top = 56, 14, 110
    p = Page("osmap", "4. OpenStack adapter mapping", 1169, top + len(MAP) * (rh + gap) + 60)
    p.vertex("Moving to OpenStack: three adapters change, the crews, schemas and knowledge base do not",
             30, 18, 1100, 32, text_style(18))
    for x, w, t in [(40, 330, "AWS PoC component"), (440, 220, "Adapter interface"), (720, 400, "OpenStack equivalent")]:
        p.vertex(t, x, 66, w, 28, text_style(12, True, "center", QUIET))
    for i, (fn, aws, os_, ad) in enumerate(MAP):
        y = top + i * (rh + gap)
        fill, stroke, font = PAL[ADAPTER_COLOR[ad]]
        a = p.vertex(lbl(fn, aws), 40, y, 330, rh, box_style("#FFFFFF", "#607D8B"))
        m = p.vertex(f"<b>{ad}</b>", 440, y + 10, 220, rh - 20, box_style(fill, stroke, 1.5, font).replace("arcSize=14", "arcSize=50"))
        o = p.vertex(lbl(fn, os_), 720, y, 400, rh, box_style("#FFFFFF", stroke))
        st = ("edgeStyle=none;html=1;endArrow=block;endFill=1;strokeColor=#90A4AE;strokeWidth=1.25;"
              "exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
        p.edge(a, m, "", st)
        p.edge(m, o, "", st)
    return p


def write_drawio():
    pages = [page_arch(), page_flow(), page_seq(), page_map()]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="app.diagrams.net" modified="{now}" '
           f'agent="OpsAgent design generator" version="24.7.0" type="device" pages="{len(pages)}">'
           + ''.join(p.xml() for p in pages) + '</mxfile>\n')
    with open(os.path.join(OUT, "opsagent-architecture.drawio"), "w", encoding="utf-8") as f:
        f.write(xml)


# ---------- standalone SVGs ----------
def svg_text(x, y, s, size=12, weight=400, fill=INK, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{E(s)}</text>')


ARROW_DEFS = ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
              'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#5F6B7A"/></marker>'
              '<marker id="open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
              'orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="none" stroke="#5F6B7A" stroke-width="1.5"/>'
              '</marker></defs>')


def write_arch_svg():
    bands, bottom = arch_layout()
    W, H = 1160, int(bottom + 40)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{SVGFONT}" role="img" aria-label="{E(TITLE)}">', ARROW_DEFS,
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         svg_text(30, 40, TITLE, 18, 700), svg_text(30, 60, SUBTITLE, 11, 400, QUIET)]
    for i, b in enumerate(bands):
        fill, stroke, font = PAL[b["key"]]
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#FFFFFF" stroke="{stroke}" stroke-width="1.5"/>')
        o.append(f'<path d="M{x+6} {y} H{x+w-6} a6 6 0 0 1 6 6 V{y+32} H{x} V{y+6} a6 6 0 0 1 6 -6 z" fill="{fill}"/>')
        o.append(f'<path d="M{x} {y+32} H{x+w}" stroke="{stroke}" stroke-width="1.5"/>')
        o.append(svg_text(x + 12, y + 21, b["title"], 13, 700, font))
        for name, body, bx, by, bw, bh in b["boxes"]:
            acc = name in ACCENT
            o.append(f'<rect x="{bx:.1f}" y="{by}" width="{bw:.1f}" height="{bh}" rx="8" '
                     f'fill="{ACCENT_FILL if acc else "#FFFFFF"}" stroke="{ACCENT_STROKE if acc else stroke}" '
                     f'stroke-width="{2.5 if acc else 1.5}"/>')
            lines = body.split("<br>")
            total = 1 + len(lines)
            y0 = by + bh / 2 - (total - 1) * 8 + 4
            o.append(svg_text(round(bx + bw / 2, 1), y0, name, 13, 700, INK, "middle"))
            for li, ln in enumerate(lines):
                o.append(svg_text(round(bx + bw / 2, 1), y0 + 17 * (li + 1), ln, 11.5, 400, QUIET, "middle"))
        label = ARCH_EDGES[i]
        if label:
            nb = bands[i + 1]
            y1, y2 = y + h, nb["y"]
            o.append(f'<path d="M{W/2} {y1} V{y2}" stroke="#5F6B7A" stroke-width="1.5" fill="none" marker-end="url(#arrow)"/>')
            o.append(svg_text(W / 2 + 10, (y1 + y2) / 2 + 4, label, 11.5, 400, QUIET))
    o.append('</svg>\n')
    with open(os.path.join(OUT, "opsagent-architecture.svg"), "w", encoding="utf-8") as f:
        f.write("\n".join(o))


def write_seq_svg():
    W, H = SEQ_X0 + len(PARTS) * SEQ_SP + 20, SEQ_TOP + SEQ_H + 40
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'font-family="{SVGFONT}" role="img" aria-label="OpsAgent sequence: alarm to knowledge write-back">', ARROW_DEFS,
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         svg_text(30, 36, "Sequence: alarm to approved fix to knowledge write-back (target times for the demo OOM)", 18, 700)]
    for m in MSGS:
        if m[0] == "par":
            o.append(f'<rect x="{PAR_X1}" y="{m[1]}" width="{PAR_X2-PAR_X1}" height="{m[2]-m[1]}" fill="none" '
                     f'stroke="#90A4AE" stroke-width="1.25"/>')
            o.append(f'<path d="M{PAR_X1} {m[1]} h50 v16 l-6 6 h-44 z" fill="#ECEFF1" stroke="#90A4AE"/>')
            o.append(svg_text(PAR_X1 + 8, m[1] + 15, "par", 11, 700, "#455A64"))
    for k, name in PARTS:
        fill, stroke, font = PAL[PART_COLOR[k]]
        acc = k == "SH"
        x = PX[k]
        o.append(f'<path d="M{x} {SEQ_TOP+50} V{SEQ_TOP+SEQ_H}" stroke="#B0BEC5" stroke-dasharray="6 4"/>')
        o.append(f'<rect x="{x-SEQ_LW/2}" y="{SEQ_TOP}" width="{SEQ_LW}" height="50" rx="8" '
                 f'fill="{ACCENT_FILL if acc else fill}" stroke="{ACCENT_STROKE if acc else stroke}" stroke-width="1.5"/>')
        lines = name.split("<br>")
        y0 = SEQ_TOP + 25 - (len(lines) - 1) * 7 + 4
        for li, ln in enumerate(lines):
            o.append(svg_text(x, y0 + 15 * li, ln, 12, 700, font, "middle"))
    for m in MSGS:
        if m[0] == "par":
            continue
        if m[0] == "sep":
            o.append(f'<path d="M{PAR_X1} {m[1]} H{PAR_X2}" stroke="#90A4AE" stroke-dasharray="6 4"/>')
            o.append(svg_text(PAR_X1 + 8, m[1] + 14, m[2], 10.5, 700, "#455A64"))
            continue
        y, a, b, label, ret = m
        xa, xb = PX[a], PX[b]
        dash = ' stroke-dasharray="6 4"' if ret else ''
        o.append(f'<path d="M{xa} {y} H{xb}" stroke="#5F6B7A" stroke-width="1.5" fill="none"{dash} '
                 f'marker-end="url(#{"open" if ret else "arrow"})"/>')
        tw = len(label) * 6.2 + 10
        cx = (xa + xb) / 2
        o.append(f'<rect x="{cx - tw/2:.1f}" y="{y-17}" width="{tw:.1f}" height="15" fill="#FFFFFF"/>')
        o.append(svg_text(cx, y - 5, label, 11, 400, INK, "middle"))
    o.append('</svg>\n')
    with open(os.path.join(OUT, "opsagent-sequence.svg"), "w", encoding="utf-8") as f:
        f.write("\n".join(o))


write_drawio()
write_arch_svg()
write_seq_svg()
print("ok", sorted(os.listdir(OUT)))
