"""OpsAgent crew / agent / tool map as a draw.io (mxGraph) file."""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("opsagent-crew-agent-tool-map.drawio")
FONT = "fontFamily=Helvetica;"
INK, QUIET, LINE = "#1F2933", "#52606D", "#CBD2D9"
CORAL = "#FF5A50"
PEN = "✎"

cells, _id = [], [1]


def nid():
    _id[0] += 1
    return f"c{_id[0]}"


def v(label, x, y, w, h, style):
    i = nid()
    lab = escape(label, {'"': "&quot;"})
    cells.append(f'<mxCell id="{i}" value="{lab}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry"/></mxCell>')
    return i


def edge(x1, y1, x2, y2, style):
    cells.append(f'<mxCell id="{nid()}" style="{style}" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                 f'<mxPoint x="{x1:.1f}" y="{y1:.1f}" as="sourcePoint"/><mxPoint x="{x2:.1f}" y="{y2:.1f}" as="targetPoint"/>'
                 f'</mxGeometry></mxCell>')


def rect(x, y, w, h, fill, stroke, sw=1, rx=1, extra=""):
    return v("", x, y, w, h, f"rounded={rx};arcSize=6;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={sw};{extra}")


def text(label, x, y, w, h, size=11, color=INK, bold=False, align="left", valign="middle", extra=""):
    return v(label, x, y, w, h, f"text;html=1;align={align};verticalAlign={valign};fontSize={size};fontColor={color};"
             f"fontStyle={1 if bold else 0};whiteSpace=wrap;overflow=hidden;{FONT}{extra}")


def aws_icon(res, color, x, y, s=22):
    return v("", x, y, s, s, f"outlineConnect=0;fontColor=#232F3E;fillColor={color};strokeColor=#ffffff;dashed=0;"
             f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;aspect=fixed;"
             f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};")


def img_icon(path, x, y, s=22):
    return v("", x, y, s, s, f"image;aspect=fixed;html=1;image={path};")


def dot(color, x, y, s=10):
    return v("", x, y, s, s, f"ellipse;fillColor={color};strokeColor=none;")


# ------------------------------------------------------------------ data
AWS_MGMT, AWS_COMPUTE, AWS_SEC = "#E7157B", "#ED7100", "#DD344C"
CREWS = [
    dict(name="Triage crew", key="triage", color="#3E6FA7", tint="#EEF3FA", steps="triage",
         goal="Parse the raw event, set severity, classify by rule before any LLM call",
         agents=[("Event Analyst", "parses the raw event, scores severity, classifies deterministically")],
         tools=[("Regex log parser (OOM, systemd lines)", ("dot", "#3776AB")),
                ("EC2 DescribeInstances and tags", ("aws", "ec2", AWS_COMPUTE)),
                ("Leak slope and restart counter", ("dot", "#3E6FA7")),
                ("Rule-based classification: reason, confidence", ("dot", "#3E6FA7"))],
         writes="triage-1.0", iam="opsagent-reader"),
    dict(name="Diagnostics crew", key="diag", color="#D9710A", tint="#FFF4E8", steps="diagnose",
         goal="RCA from the event evidence, cited from docs; fixes ranked immediate and durable",
         agents=[("Evidence Correlator", "timeline from the event's metrics, OOM and systemd records"),
                 ("RCA Engineer", "hypothesis, citations from KB and AWS docs"),
                 ("Remediation Advisor", "ranks immediate (infra) and durable (code) fixes")],
         tools=[("Triage evidence: metrics, OOM, systemd, errors", ("dot", "#D9710A")),
                ("AWS Documentation MCP server", ("dot", "#ED7100")),
                ("Knowledge base search (hybrid)", ("dot", "#2E7D32")),
                ("Closed-incident lookup (kb-record)", ("dot", "#2E7D32"))],
         writes="diagnosis-1.0", iam="opsagent-reader"),
    dict(name="Code Correlation crew", key="code", color="#6F42C1", tint="#F3EEFB", steps="correlate_code",
         goal="Code path behind the log line; verdict code, infra or shared",
         agents=[("Repo Navigator", "maps the app tag to a repository, finds the code path"),
                 ("Code Analyst", "unbounded growth, missing eviction, N+1, busy loops"),
                 ("Ownership Adjudicator", "verdict with confidence and a developer action")],
         tools=[("GitHub MCP server (read-only)", ("dot", "#24292F")),
                ("Shallow clone and grep", ("dot", "#24292F")),
                ("Commit history, last 14 days", ("dot", "#24292F")),
                ("app tag to repository map (config)", ("dot", "#6F42C1")),
                ("Pattern checks: leak, N+1, busy loop", ("dot", "#6F42C1"))],
         writes="code-correlation-1.0", iam="opsagent-code-reader (GitHub App)"),
    dict(name="Incident Bridge crew", key="bridge", color="#5B5FC7", tint="#EEEFFB", steps="page_stage1, page_stage2",
         goal="Page L2 at T+60 s, then enrich with RCA, verdict and fix",
         agents=[("Incident Writer", "fills deterministic templates, writes the narrative"),
                 ("Notifier", "delivers, records receipts, updates the Teams card")],
         tools=[("Teams incoming webhook, Adaptive Card 1.5", ("dot", "#5B5FC7")),
                ("SMTP relay, smtplib with STARTTLS", ("dot", "#607D8B")),
                ("xMatters trigger API, voice page", ("dot", "#00A3E0")),
                ("Approve / Reject signed links", ("dot", "#5B5FC7")),
                ("Langfuse trace link", ("dot", "#7C3AED"))],
         writes="incident-package-1.0", iam="opsagent-notifier"),
    dict(name="Self-Healing crew", key="heal", color="#E65100", tint="#FFF1E6", steps="plan_remediation, execute_remediation", phase2=True,
         goal="Bounded fix from the catalog, applied only after a human approval",
         agents=[("Remediation Planner", "picks a catalog action, computes parameters, dry-run"),
                 ("Change Executor  " + PEN, "executes after approval, one action per approval"),
                 ("Verifier", "health check, rollback on failure, cooldown")],
         tools=[("Action catalog, 7 allow-listed actions", ("dot", "#E65100")),
                ("SSM Run Command  " + PEN, ("aws", "systems_manager", AWS_MGMT)),
                ("EC2 ModifyInstanceAttribute  " + PEN, ("aws", "ec2", AWS_COMPUTE)),
                ("Auto Scaling SetDesiredCapacity  " + PEN, ("aws", "auto_scaling2", AWS_COMPUTE)),
                ("Terraform PR generator, never apply", ("dot", "#7B42BC")),
                ("Health verify: CloudWatch and systemctl", ("aws", "cloudwatch", AWS_MGMT))],
         writes="remediation-plan-1.0, remediation-result-1.0", iam="opsagent-remediator, after approval only"),
    dict(name="Knowledge crew", key="kb", color="#2E7D32", tint="#EAF5EB", steps="close, plus weekly schedule",
         goal="Keep official docs fresh; write incidents back with a human label",
         agents=[("KB Curator", "weekly: fetch, diff, chunk, embed, version"),
                 ("Incident Librarian", "on close: RCA, fix, outcome, accept or reject label")],
         tools=[("Docs fetcher: systemd, kernel, OpenStack", ("dot", "#2E7D32")),
                ("Client runbooks, access-controlled", ("dot", "#2E7D32")),
                ("Chunker 600 / 80 and embedder", ("dot", "#0078D4")),
                ("Vector store write  " + PEN, ("dot", "#2E7D32")),
                ("Human label capture from the Teams card", ("dot", "#5B5FC7"))],
         writes="kb-record-1.0", iam="opsagent-kb-writer"),
]
STEPS = [("intake", "@start", None), ("triage", "@listen(intake)", "triage"), ("severity?", "@router", None),
         ("page_stage1", "critical", "bridge"), ("diagnose", "critical", "diag"), ("correlate_code", "critical", "code"),
         ("page_stage2", "and_(diagnose, correlate)", "bridge"), ("plan_remediation", "@listen(diagnose)", "heal"),
         ("approval gate", "human in the loop", "heal"), ("execute_remediation", "approved", "heal"), ("close", "@listen", "kb")]
COLOR = {c["key"]: (c["color"], c["tint"]) for c in CREWS}

# ------------------------------------------------------------------ layout
X0, PW = 40, 1840
text("OpsAgent  ·  Crews, agents and tools", X0, 22, 1100, 30, 20, INK, True)
text("Six CrewAI crews orchestrated by one IncidentFlow. Every agent runs on Azure OpenAI gpt-4o; "
     "tools are read-only everywhere except the approval-gated Self-Healing executor.",
     X0, 52, 1400, 20, 11, QUIET)
text("Rev 1.0  ·  15 Nov 2026", X0 + PW - 300, 30, 300, 20, 11, QUIET, align="right")

# flow band
BY, BH = 92, 84
rect(X0, BY, PW, BH, "#FFFFFF", CORAL, 1.5, 1)
text("INCIDENTFLOW  ·  persisted Pydantic state, severity router, and_ join, pause for approval", X0 + 14, BY + 2, 900, 20, 10, CORAL, True)
n = len(STEPS)
cw, gapw = 150, (PW - 28 - n * 150) / (n - 1)
for i, (name, tag, key) in enumerate(STEPS):
    x = X0 + 14 + i * (cw + gapw)
    col, tint = COLOR.get(key, (CORAL, "#FFF0EF"))
    style = (f"rounded=1;arcSize=14;whiteSpace=wrap;html=1;fillColor={tint};strokeColor={col};strokeWidth=1.25;"
             f"fontSize=10.5;fontColor={INK};fontStyle=1;{FONT}")
    if key == "heal":
        style += "dashed=1;dashPattern=5 4;"
        tag = tag + "  ·  phase 2"
    if name == "approval gate":
        style += "dashed=1;dashPattern=4 3;strokeWidth=1.75;"
    if name == "severity?":
        style = (f"rhombus;whiteSpace=wrap;html=1;fillColor={tint};strokeColor={col};strokeWidth=1.25;fontSize=10;"
                 f"fontColor={INK};fontStyle=1;{FONT}")
    lbl = f'{name}<br><font style="font-size:8.5px;font-weight:normal;color:{QUIET}">{tag}</font>'
    v(lbl, x, BY + 28, cw, 44, style)
    if i < n - 1:
        edge(x + cw, BY + 50, x + cw + gapw, BY + 50, f"endArrow=blockThin;endFill=1;strokeColor=#9AA5B1;strokeWidth=1;html=1;")

# lanes
LY, LH, LW = 200, 552, 292
LG = (PW - 6 * LW) / 5
for i, c in enumerate(CREWS):
    x = X0 + i * (LW + LG)
    col, tint = c["color"], c["tint"]
    p2 = c.get("phase2", False)
    rect(x, LY, LW, LH, tint, col, 1.25, 1, "dashed=1;dashPattern=8 5;" if p2 else "")
    rect(x, LY, LW, 42, col, col, 1, 1, "arcSize=4;")
    if p2:
        text("PHASE 2 · after the PoC", x + LW - 150, LY + 3, 138, 22, 9.5, "#FFFFFF", True, align="right")
    rect(x, LY + 26, LW, 16, col, col, 0, 0)
    text(c["name"], x + 12, LY + 3, LW - 24, 22, 12.5, "#FFFFFF", True)
    text(f"Flow step: {c['steps']}", x + 12, LY + 22, LW - 24, 18, 9, "#FFFFFF")
    text(c["goal"], x + 12, LY + 46, LW - 24, 32, 9.5, QUIET, valign="top", extra="spacingTop=4;")
    # agents
    ay = LY + 84
    text("AGENTS", x + 12, ay - 2, 120, 14, 8.5, col, True)
    text("LLM: azure/gpt-4o", x + LW - 132, ay - 2, 120, 14, 8.5, QUIET, align="right")
    ay += 14
    for j, (an, role) in enumerate(c["agents"]):
        y = ay + j * 60
        rect(x + 12, y, LW - 24, 52, "#FFFFFF", col, 1, 1)
        rect(x + 12, y + 1, 5, 50, col, col, 0, 0)
        initials = "".join(w[0] for w in an.replace(PEN, "").split() if w[0].isalpha())[:2]
        v(initials, x + 25, y + 10, 32, 32, f"ellipse;whiteSpace=wrap;html=1;fillColor={tint};strokeColor={col};"
          f"strokeWidth=1;fontSize=11;fontStyle=1;fontColor={col};{FONT}")
        text(an, x + 66, y + 5, LW - 86, 20, 11, INK, True)
        text(role, x + 66, y + 24, LW - 86, 26, 9, QUIET, valign="top")
    # tools
    ty = LY + 98 + 3 * 60 + 8
    text("TOOLS", x + 12, ty - 2, 120, 14, 8.5, col, True)
    text("read-only unless " + PEN, x + LW - 132, ty - 2, 120, 14, 8.5, QUIET, align="right")
    ty += 14
    for j, (tn, icon) in enumerate(c["tools"]):
        y = ty + j * 30
        wr = PEN in tn
        rect(x + 12, y, LW - 24, 25, "#FFFFFF", "#F2B88A" if wr else LINE, 1.25 if wr else 1, 1, "arcSize=20;")
        if icon[0] == "aws":
            aws_icon(icon[1], icon[2], x + 18, y + 2.5, 20)
        else:
            dot(icon[1], x + 23, y + 7.5, 10)
        text(tn, x + 44, y, LW - 60, 25, 9.5, INK)
    # footer
    fy = LY + LH - 60
    edge(x + 12, fy, x + LW - 12, fy, f"endArrow=none;strokeColor={col};strokeWidth=1;opacity=50;html=1;")
    text(f'<b>Writes</b>&nbsp; <font face="Consolas">{c["writes"]}</font>', x + 12, fy + 6, LW - 24, 22, 9, INK)
    aws_icon("identity_and_access_management", AWS_SEC, x + 12, fy + 31, 18)
    text(f'<font face="Consolas">{c["iam"]}</font>', x + 34, fy + 29, LW - 46, 22, 8.5, QUIET)

# foundation band
FY, FH = LY + LH + 26, 110
rect(X0, FY, PW, FH, "#F5F7FA", LINE, 1, 1)
text("SHARED FOUNDATION  ·  used by every crew", X0 + 14, FY + 2, 600, 20, 10, QUIET, True)
FOUND = [
    ("Azure OpenAI", 'gpt-4o via CrewAI LLM(model="azure/gpt-4o"); embeddings text-embedding-3-small or local bge-small',
     ("img", "img/lib/azure2/ai_machine_learning/Azure_OpenAI.svg"), "#0078D4"),
    ("CrewAI 1.x runtime", "Flows, Crews, output_pydantic on every task, MCP tool adapter, LiteLLM routing", ("dot", CORAL), CORAL),
    ("Vector store", "Chroma for the PoC, pgvector in production; chunks keyed by source, version and anchor", ("dot", "#2E7D32"), "#2E7D32"),
    ("PostgreSQL", "Flow state, resumable after restart; append-only incident log; approvals", ("dot", "#336791"), "#336791"),
    ("Langfuse + OpenTelemetry", "one span per step, crew, task and tool call; tokens, latency and cost per incident", ("dot", "#7C3AED"), "#7C3AED"),
    ("Secrets", "AWS Secrets Manager or Azure Key Vault: webhook URL, SMTP, xMatters key, GitHub App",
     ("aws", "secrets_manager", AWS_SEC), AWS_SEC),
    ("IAM + CloudTrail", "one role per crew; the remediator role is assumed only after approval; every call audited",
     ("aws", "cloudtrail", AWS_MGMT), AWS_MGMT),
]
fg = 14
fw = (PW - 28 - 6 * fg) / 7
for i, (nm, d, icon, col) in enumerate(FOUND):
    x = X0 + 14 + i * (fw + fg)
    rect(x, FY + 24, fw, 74, "#FFFFFF", LINE, 1, 1)
    rect(x, FY + 24, fw, 4, col, col, 0, 0)
    if icon[0] == "aws":
        aws_icon(icon[1], icon[2], x + 10, FY + 38, 24)
    elif icon[0] == "img":
        img_icon(icon[1], x + 10, FY + 38, 24)
    else:
        dot(icon[1], x + 16, FY + 44, 12)
    text(nm, x + 42, FY + 32, fw - 50, 20, 11, INK, True)
    text(d, x + 42, FY + 50, fw - 50, 44, 8.5, QUIET, valign="top")

# legend + title block
GY = FY + FH + 20
text("LEGEND", X0, GY, 100, 16, 9, QUIET, True)
lx = X0
for c in CREWS:
    rect(lx, GY + 22, 14, 14, c["tint"], c["color"], 1.25, 1)
    short = c["name"].replace(" crew", "")
    text(short, lx + 18, GY + 20, 130, 18, 9.5, INK)
    lx += 24 + 6.4 * len(short) + 14
text(PEN + "  write tool, used only inside the approval gate", X0, GY + 42, 320, 16, 9.5, INK)
text("Flow chip colour = crew it invokes.  Dashed lane and chips = phase 2, after the PoC.  AWS icons = managed services called through boto3 or SSM.",
     X0, GY + 60, 820, 16, 9.5, QUIET)

TX, TW = X0 + PW - 560, 560
rect(TX, GY, TW, 80, "#FFFFFF", INK, 1, 0)
rows = [("Project", "OpsAgent  ·  Agentic L1/L2 incident response"),
        ("Drawing", "Crew, agent and tool map  ·  sheet 1 of 1"),
        ("Organisation", "The Ark Enterprise"),
        ("Revision", "1.0  ·  15 November 2026  ·  Draft for client PoC")]
for i, (k, val) in enumerate(rows):
    y = GY + i * 20
    if i:
        edge(TX, y, TX + TW, y, f"endArrow=none;strokeColor={LINE};strokeWidth=1;html=1;")
    text(k, TX + 10, y, 90, 20, 9, QUIET, True)
    text(val, TX + 104, y, TW - 114, 20, 9.5, INK)
edge(TX + 96, GY, TX + 96, GY + 80, f"endArrow=none;strokeColor={LINE};strokeWidth=1;html=1;")

PH = int(GY + 80 + 40)
xml = (f'<mxfile host="app.diagrams.net" modified="2026-11-15T00:00:00.000Z" agent="OpsAgent generator" version="24.7.17" type="device">'
       f'<diagram id="crew-map" name="Crews, agents and tools"><mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" '
       f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1920" pageHeight="{PH}" math="0" shadow="0" '
       f'background="#FFFFFF"><root><mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>')
OUT.write_text(xml, encoding="utf-8")
print("wrote", OUT, len(cells), "cells; page 1920 x", PH)
