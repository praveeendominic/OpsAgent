// OpsAgent PoC proposal deck. White background, 16:9 wide. Run with NODE_PATH pointing at the folder's node_modules.
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("C:/Users/prave/.claude/skills/synced/f6222e0a-f85b-4949-8492-ac05ebae7d26_8f14e011-ef08-4753-b821-55be58509301/pptx/scripts/apply_theme.js");

const OUT = process.argv[2] || path.join(__dirname, "OpsAgent-PoC-Deck.pptx");

const THEME = {
  name: "OpsAgent",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1F2933", lt1: "FFFFFF", dk2: "52606D", lt2: "F5F7FA",
    accent1: "FF5A50", accent2: "3E6FA7", accent3: "2E7D32", accent4: "D9710A", accent5: "6F42C1", accent6: "5B5FC7",
    hlink: "3E6FA7", folHlink: "6F42C1",
  },
};
const HX = THEME.colors; // hex copies for options that take hex only (tables, lines)
const LINE = "CBD2D9", CARD_LINE = "E1E5EA";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "OpsAgent: agentic AI automation for L1/L2 incident response, PoC proposal";
pres.author = "The Ark Enterprise";
pres.company = "The Ark Enterprise";
const C = pres.SchemeColor;

const FOOT = "OpsAgent  ·  Agentic L1/L2 incident response  ·  The Ark Enterprise";
pres.defineSlideMaster({
  title: "content",
  background: { color: "FFFFFF" },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.42, w: 12.1, h: 0.75, fontSize: 30, bold: true, color: C.text1, margin: 0, valign: "top", align: "left" }, text: "Title" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: 0.6, y: 1.12, w: 12.1, h: 0.4, fontSize: 14, color: C.text2, margin: 0, valign: "top" }, text: "Subtitle" } },
    { text: { text: FOOT, options: { x: 0.6, y: 7.02, w: 9, h: 0.3, fontSize: 9, color: C.text2, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.3, fontSize: 9, color: C.text2, align: "right" },
});
pres.defineSlideMaster({
  title: "cover",
  background: { color: "FFFFFF" },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.9, y: 2.3, w: 11.5, h: 1.1, fontSize: 48, bold: true, color: C.text1, margin: 0, valign: "top", align: "left" }, text: "Title" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: 0.9, y: 3.45, w: 11.5, h: 0.6, fontSize: 22, color: C.text2, margin: 0, valign: "top" }, text: "Subtitle" } },
    { placeholder: { options: { name: "meta", type: "body", x: 0.9, y: 4.25, w: 11.5, h: 0.4, fontSize: 14, color: C.text2, margin: 0, valign: "top" }, text: "Meta" } },
  ],
});
pres.defineSlideMaster({
  title: "section",
  background: { color: "FFFFFF" },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.9, y: 2.55, w: 11.5, h: 0.4, fontSize: 14, bold: true, color: C.accent1, margin: 0, valign: "top", charSpacing: 2 }, text: "Kicker" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.9, y: 3.0, w: 11.5, h: 1.0, fontSize: 40, bold: true, color: C.text1, margin: 0, valign: "top", align: "left" }, text: "Title" } },
    { placeholder: { options: { name: "subtitle", type: "body", x: 0.9, y: 4.05, w: 10.5, h: 0.8, fontSize: 16, color: C.text2, margin: 0, valign: "top" }, text: "Subtitle" } },
    { text: { text: FOOT, options: { x: 0.6, y: 7.02, w: 9, h: 0.3, fontSize: 9, color: C.text2, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.3, fontSize: 9, color: C.text2, align: "right" },
});

// ------------------------------------------------------------------ helpers
let sec = "";
const slide = (master = "content") => pres.addSlide({ masterName: master, sectionTitle: sec });
const section = (title) => { sec = title; pres.addSection({ title }); };
const card = (s, x, y, w, h, name, fill = C.background2, line = CARD_LINE) =>
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: line, width: 0.75 }, objectName: name });
const text = (s, t, o) => s.addText(t, Object.assign({ margin: 0, isTextBox: true, valign: "top" }, o));
const pill = (s, x, y, w, label, col, name) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.3, rectRadius: 0.15, fill: { color: col }, line: { color: col, width: 0 }, objectName: name });
  text(s, label, { x, y, w, h: 0.3, fontSize: 10.5, bold: true, color: C.background1, align: "center", valign: "middle", objectName: name + "-t" });
};
const badge = (s, x, y, d, label, col, name) => {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: col }, line: { color: col, width: 0 }, objectName: name });
  text(s, label, { x, y, w: d, h: d, fontSize: d > 0.42 ? 14 : 12, bold: true, color: C.background1, align: "center", valign: "middle", objectName: name + "-t" });
};
const W = 12.13, X0 = 0.6;
const sectionSlide = (kicker, title, sub) => {
  const s = slide("section");
  s.addText(kicker, { placeholder: "kicker" });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "subtitle" });
  return s;
};

// ================================================================== 1 cover
section("Cover");
{
  const s = slide("cover");
  s.addText("OpsAgent", { placeholder: "title" });
  s.addText("Agentic AI automation for L1/L2 incident response", { placeholder: "subtitle" });
  s.addText("Proof of concept proposal  ·  The Ark Enterprise  ·  November 2026", { placeholder: "meta" });
  const crews = [["Triage", C.accent2], ["Diagnostics", C.accent4], ["Code Correlation", C.accent5], ["Incident Bridge", C.accent6], ["Self-Healing", C.accent1], ["Knowledge", C.accent3]];
  crews.forEach(([n, col], i) => {
    const x = 0.9 + i * 1.95;
    s.addShape(pres.shapes.OVAL, { x, y: 5.5, w: 0.22, h: 0.22, fill: { color: col }, line: { color: col, width: 0 }, objectName: `cover-dot-${i}` });
    text(s, n, { x: x + 0.3, y: 5.48, w: 1.6, h: 0.28, fontSize: 12, color: C.text2, valign: "middle", objectName: `cover-crew-${i}` });
  });
  s.addNotes("Cover. The six crews along the bottom are the cast of the story; Self-Healing is shown because it is where the roadmap ends, not where the PoC starts.");
}

// ================================================================== 2 agenda
{
  const s = slide();
  s.addText("Agenda", { placeholder: "title" });
  s.addText("What we will cover in the next forty minutes", { placeholder: "subtitle" });
  const items = [
    ["Background", "what happened and what triggered this analysis"],
    ["Our observation", "what is in place, where the gaps are"],
    ["Our point of view", "what agentic AI automation changes in L1/L2 operations"],
    ["Architecture for the PoC", "the Flow, the crews, the agents and their tools"],
    ["Future work", "approved self-healing, then the OpenStack private cloud"],
    ["Asks and next steps", "what we need from you to start"],
  ];
  items.forEach(([h, d], i) => {
    const y = 1.8 + i * 0.78;
    badge(s, X0, y, 0.42, String(i + 1), i === 4 ? C.accent1 : C.accent2, `ag-${i}`);
    text(s, [{ text: h, options: { bold: true, color: C.text1, fontSize: 16 } }, { text: "    " + d, options: { color: C.text2, fontSize: 13 } }],
      { x: X0 + 0.6, y, w: 11, h: 0.42, valign: "middle", objectName: `ag-${i}-t` });
  });
  s.addNotes("Keep this to thirty seconds. The structure is problem, point of view, architecture, then what sits beyond the PoC.");
}

// ================================================================== 3 background
section("Background");
{
  const s = slide();
  s.addText("Background: what triggered this analysis", { placeholder: "title" });
  s.addText("A production incident, what the platform offers on its own, and the question that leaves open", { placeholder: "subtitle" });
  const cols = [
    ["1", "The incident", C.accent1, [
      "An application on EC2 is killed by the kernel OOM killer after its memory grows for a few minutes.",
      "systemd restarts it, so the service looks healthy between crashes and the fault hides until the next kill.",
      "Finding the cause takes an engineer 20 to 60 minutes of reading logs and metrics by hand, every time.",
    ]],
    ["2", "What AWS gives you today", C.accent3, [
      "The CloudWatch agent ships memory, CPU and logs; alarms fire on thresholds; EventBridge can trigger on the state change.",
      "Out of the box that produces a notification: a metric crossed a line on an instance. No evidence, no cause, no owner.",
      "Systems Manager can run a scripted fix, but only for a symptom someone already scripted.",
    ]],
    ["3", "The open question", C.accent2, [
      "Can the stage after detection, diagnosis, attribution, paging and the fix, be automated safely?",
      "Not with more scripts: the symptoms vary, the evidence is spread across logs, metrics, docs and code.",
      "This proposal answers it with an event capture path plus an agentic workflow, shown first as a focused proof of concept.",
    ]],
  ];
  const gap = 0.3, cw = (W - 2 * gap) / 3;
  cols.forEach(([n, h, col, lines], i) => {
    const x = X0 + i * (cw + gap), y = 1.72, hgt = 4.5;
    card(s, x, y, cw, hgt, `bg-${i}`);
    badge(s, x + 0.25, y + 0.25, 0.46, n, col, `bg-${i}-n`);
    text(s, h, { x: x + 0.85, y: y + 0.25, w: cw - 1.1, h: 0.46, fontSize: 18, bold: true, color: C.text1, valign: "middle", objectName: `bg-${i}-h` });
    text(s, lines.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < lines.length - 1 } })),
      { x: x + 0.25, y: y + 0.95, w: cw - 0.5, h: hgt - 1.2, fontSize: 14, color: C.text2, paraSpaceAfter: 12, objectName: `bg-${i}-b` });
  });
  s.addNotes("One slide of history. The incident is real and repeatable. Nothing is built yet: the middle card is what AWS provides natively, and the gap is everything from evidence collection onward. If there are figures from the analysis, such as number of occurrences or hours spent, say them here.");
}

// ================================================================== 4 observation
section("Our observation");
{
  const s = slide();
  s.addText("Observation: detection is solved, diagnosis is not", { placeholder: "title" });
  s.addText("What the AWS platform provides on its own against what an incident still needs from a person", { placeholder: "subtitle" });
  const inPlace = [
    ["Metrics and logs", "the CloudWatch agent ships memory, CPU and log files from every instance"],
    ["Threshold alarms", "CloudWatch alarms on mem_used_percent and CPU, instance status checks"],
    ["Event triggers", "EventBridge rules fire on an alarm state change within seconds"],
    ["Notifications", "SNS can email or message a channel that a threshold was crossed"],
    ["Scripted runbooks", "Systems Manager Automation can run a fixed script for a known symptom"],
  ];
  const gaps = [
    ["Evidence", "the alarm says a line was crossed; nobody gathers the logs, metrics and process state around it"],
    ["Diagnosis", "root cause is worked out by hand, without citations, and differs by engineer"],
    ["Attribution", "nobody states whether the fault is code or infrastructure, so the fix bounces between teams"],
    ["Paging", "L2 hears about it when a person decides to page, not when the alarm fires"],
    ["Learning", "the incident closes in a chat thread; the next one starts from zero and nothing is measured"],
  ];
  const gap = 0.3, cw = (W - gap) / 2, y0 = 1.72, hgt = 5.0;
  [["NATIVE AWS, AVAILABLE TODAY", inPlace, C.accent3, "ok"], ["THE GAP OPSAGENT CLOSES", gaps, C.accent1, "gap"]].forEach(([h, rows, col, key], i) => {
    const x = X0 + i * (cw + gap);
    card(s, x, y0, cw, hgt, `obs-${key}`);
    text(s, h, { x: x + 0.25, y: y0 + 0.2, w: 6, h: 0.3, fontSize: 11, bold: true, color: col, charSpacing: 2, objectName: `obs-${key}-h` });
    rows.forEach(([k, v], j) => {
      const y = y0 + 0.62 + j * 0.84;
      s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.03, w: 0.26, h: 0.26, fill: { color: col }, line: { color: col, width: 0 }, objectName: `obs-${key}-${j}-d` });
      text(s, key === "ok" ? "\u2713" : "\u2715", { x: x + 0.25, y: y + 0.03, w: 0.26, h: 0.26, fontSize: 11, bold: true, color: C.background1, align: "center", valign: "middle", objectName: `obs-${key}-${j}-m` });
      text(s, [{ text: k, options: { bold: true, color: C.text1, breakLine: true } }, { text: v, options: { color: C.text2 } }],
        { x: x + 0.65, y, w: cw - 0.9, h: 0.78, fontSize: 12.5, objectName: `obs-${key}-${j}-t` });
    });
  });
  s.addNotes("Left column is what AWS provides without writing anything. Right column is the gap this proposal closes. If the analysis has data points, put them against the right-hand rows: time per diagnosis, number of repeat incidents, hand-offs between teams.");
}

// ================================================================== 5 pipeline
{
  const s = slide();
  s.addText("Event capture: from a metric breach to a routed event", { placeholder: "title" });
  s.addText("Native AWS signals trigger it; the enricher and the Flow intake are part of what we propose", { placeholder: "subtitle" });
  const bx = 0.6, bw = 5.9, colW = 2.8, colGap = 0.3, cL = bx, cR = bx + colW + colGap, bh = 0.7, step = 1.0, y1 = 1.62;
  const edge = "9AA5B1";
  const box = (x, y, w, head, sub, col, name) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: bh, rectRadius: 0.08, fill: { color: "FFFFFF" }, line: { color: col, width: 1.5 }, objectName: name });
    text(s, [{ text: head, options: { bold: true, color: C.text1, fontSize: 12.5, breakLine: true } }, { text: sub, options: { color: C.text2, fontSize: 10 } }],
      { x: x + 0.12, y, w: w - 0.24, h: bh, valign: "middle", align: "center", objectName: name + "-t" });
  };
  let ln = 0;
  const vline = (x, y, h, dashed) => s.addShape(pres.shapes.LINE, { x, y, w: 0, h, line: { color: edge, width: 1.25, endArrowType: "triangle", dashType: dashed ? "dash" : "solid" }, objectName: `line-${++ln}` });
  const mx = cL + colW / 2, lx = cR + colW / 2;
  box(bx, y1, bw, "EC2 instance", "application + CloudWatch agent", HX.dk2, "ec2");
  vline(mx, y1 + bh, step - bh, false); vline(lx, y1 + bh, step - bh, false);
  box(cL, y1 + step, colW, "CloudWatch metrics", "mem_used_percent, CPU", HX.accent3, "cwm");
  box(cR, y1 + step, colW, "CloudWatch Logs", "application log, /var/log/messages", HX.accent3, "cwl");
  vline(mx, y1 + step + bh, step - bh, false);
  box(cL, y1 + 2 * step, colW, "Alarm + EventBridge rule", "ALARM state change, status check", HX.accent3, "alarm");
  vline(mx, y1 + 2 * step + bh, step - bh, false);
  vline(lx, y1 + step + bh, 2 * step - bh, true);
  box(bx, y1 + 3 * step, bw, "Lambda enricher  (proposed)", "instance details, 15 min window of metrics and logs, raw-1.0 event", HX.accent1, "lambda");
  vline(bx + bw / 2, y1 + 3 * step + bh, step - bh, false);
  box(bx, y1 + 4 * step, bw, "OpsAgent Flow intake  (proposed)", "SQS intake, Triage crew: deterministic parse, rule-based classification, severity routing", HX.accent1, "intake");
  vline(bx + bw / 2, y1 + 4 * step + bh, 0.22, false);
  const ty = y1 + 4 * step + bh + 0.22;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx + 0.6, y: ty, w: bw - 1.2, h: 0.34, rectRadius: 0.17, fill: { color: "FFF0EF" }, line: { color: C.accent1, width: 1.25 }, objectName: "to-flow" });
  text(s, "triage-1.0  \u2192  Diagnostics, Code Correlation, Incident Bridge", { x: bx + 0.6, y: ty, w: bw - 1.2, h: 0.34, fontSize: 10.5, bold: true, color: C.text1, align: "center", valign: "middle", objectName: "to-flow-t" });
  const fx = 7.1, fw = 5.63, fy = 1.62, rh = 0.86;
  const fns = [
    ["Monitor", "Native. The CloudWatch agent on the instance ships memory and CPU metrics plus the application log and the system log, at one-minute resolution.", C.accent3],
    ["Detect", "Native. A threshold alarm on mem_used_percent or CPU moves to ALARM; an instance status check covers the case where the host itself is unhealthy.", C.accent3],
    ["Trigger", "Native. An EventBridge rule fires on the alarm state change, so the path reacts in seconds rather than on a polling schedule.", C.accent3],
    ["Collect", "Proposed. A small Lambda gathers instance details, the last 15 minutes of metrics and the matching log lines into one raw-1.0 event on a queue.", C.accent1],
    ["Classify", "Proposed. The Triage crew parses the raw lines with code, not a model: reason, sub-reason, confidence, severity, leak slope, restart count.", C.accent1],
    ["Route", "Proposed. The Flow routes by severity: critical fans out to Diagnostics, Code Correlation and the first page; info and warning are logged.", C.accent1],
  ];
  fns.forEach(([h, b, col], i) => {
    const y = fy + i * rh;
    pill(s, fx, y + 0.03, 0.9, h, col, `fn-${i + 1}`);
    text(s, b, { x: fx + 1.05, y, w: fw - 1.05, h: rh - 0.08, fontSize: 11, color: C.text2, objectName: `fn-${i + 1}-b` });
  });
  s.addNotes("Green is what AWS does for us today; coral is what we build. The only new infrastructure before the agents is one Lambda and one queue. Classification and routing are deterministic code inside the Flow intake, so the first model call happens only once the evidence is parsed.");
}

// ================================================================== 7 POV section + agents investigate
section("Our point of view");
sectionSlide("OUR POINT OF VIEW", "Agents investigate, people approve", "Agentic AI automation closes the gap after detection: diagnosis with evidence, attribution to code or infrastructure, a page in a minute, and a fix proposal a person can act on.")
  .addNotes("Divider. One sentence: the agents do the investigation a person does today, and the person keeps the decision.");
{
  const s = slide();
  s.addText("Agents investigate, people approve", { placeholder: "title" });
  s.addText("From alerts to resolved incidents: agentic AI automation for L1/L2 operations", { placeholder: "subtitle" });
  const rows = [
    ["The human loop today", "Alarm, logs, guesswork, a page, a manual fix. For a memory leak that cycle is 20 to 60 minutes, while the restart loop hides the fault until the next crash.", C.accent2],
    ["A team of agents, one workflow", "Triage, diagnosis, code correlation, paging and knowledge, each agent with narrow tools and narrow permissions, coordinated by one deterministic Flow that starts at the alarm.", C.accent4],
    ["Grounded, not guessed", "Diagnoses cite official documentation and the client's own runbooks through MCP servers and a knowledge base. Every closed incident is written back.", C.accent5],
    ["Human in the loop by design", "Agents read and recommend. Any change to infrastructure is made by a person; approved, automated self-healing is the phase after the PoC.", C.accent1],
    ["Observable and portable", "Every step is traced with cost per incident. The same workflow runs on AWS or an OpenStack private cloud by swapping three adapters.", C.accent3],
  ];
  const x0 = 0.6, y0 = 1.72, rowH = 1.02, circ = 0.44;
  rows.forEach(([head, body, col], i) => {
    const y = y0 + i * rowH;
    badge(s, x0, y + 0.02, circ, String(i + 1), col, `step-${i + 1}`);
    text(s, head, { x: x0 + 0.62, y, w: 6.0, h: 0.3, fontSize: 15, bold: true, color: C.text1, objectName: `head-${i + 1}` });
    text(s, body, { x: x0 + 0.62, y: y + 0.31, w: 6.0, h: 0.66, fontSize: 12, color: C.text2, objectName: `body-${i + 1}` });
  });
  card(s, 7.65, 1.55, 5.1, 5.4, "arch-card");
  s.addImage({ path: path.join(__dirname, "arch.png"), x: 7.75, y: 1.6, w: 4.9, h: 5.2, sizing: { type: "contain", w: 4.9, h: 5.2 }, objectName: "Reference architecture: detection, ingestion, six crews, actions, foundation" });
  text(s, "OpsAgent reference architecture: one Flow, six crews, from alarm to a recommended fix", { x: 7.65, y: 6.72, w: 5.1, h: 0.26, fontSize: 9.5, italic: true, color: C.text2, align: "center", objectName: "arch-caption" });
  s.addNotes("Operations fixes it tonight, developers fix it for good, and the same report tells both what to do. The right-hand figure is the OpsAgent reference architecture: detection produces one structured event, the Flow runs the crews over one persisted state, and nothing changes on a host without a person. Self-Healing is in the picture because it is the next phase, not because it runs in the PoC.");
}

// ================================================================== 8 value
{
  const s = slide();
  s.addText("What agentic automation changes", { placeholder: "title" });
  s.addText("Scripted runbooks handle the incident you already know. Agents handle the one in front of them, and show their working.", { placeholder: "subtitle" });
  const rows = [
    ["", "Scripted automation (runbooks)", "Agentic automation (OpsAgent)"],
    ["Novel symptoms", "Only patterns someone scripted in advance", "Reasons over the evidence in the event, the docs and the code"],
    ["Explanation", "A log line saying the script ran", "A cited root cause an engineer can check and challenge"],
    ["Attribution", "None; the ticket bounces between teams", "A code, infra or shared verdict with the file and symbol"],
    ["Paging", "When a person decides", "Triage facts at T+60 s, full package when the RCA lands"],
    ["Learning", "Scripts age; nobody measures them", "Incidents written back with a human label; traced and costed"],
  ];
  const tableRows = rows.map((r, i) => r.map((c, j) => ({
    text: c,
    options: {
      bold: i === 0 || j === 0, fontSize: i === 0 ? 11 : 11.5,
      color: i === 0 ? "FFFFFF" : (j === 0 ? HX.dk1 : HX.dk2),
      fill: { color: i === 0 ? (j === 2 ? HX.accent1 : HX.dk2) : (j === 2 ? "FFF0EF" : "FFFFFF") },
      valign: "middle", margin: [0.06, 0.1, 0.06, 0.1],
    },
  })));
  s.addTable(tableRows, { x: X0, y: 1.72, w: 7.6, colW: [1.45, 2.85, 3.3], rowH: 0.62, border: { type: "solid", pt: 0.75, color: CARD_LINE }, fontFace: "Calibri", objectName: "value-table" });
  const tiles = [
    ["L1 removed", "no human step between alarm and a paged, briefed L2"],
    ["about 1 min", "to the first page, with triage facts"],
    ["under 4 min", "to a cited root cause and a verdict"],
    ["compounding", "every incident makes the next diagnosis warmer"],
  ];
  const tx = 8.55, tw = 4.18, th = 1.12;
  tiles.forEach(([big, small], i) => {
    const y = 1.72 + i * (th + 0.16);
    card(s, tx, y, tw, th, `vt-${i}`, "FFFFFF", LINE);
    text(s, big, { x: tx + 0.2, y: y + 0.14, w: tw - 0.4, h: 0.46, fontSize: 22, bold: true, color: C.accent1, objectName: `vt-${i}-b` });
    text(s, small, { x: tx + 0.2, y: y + 0.62, w: tw - 0.4, h: 0.44, fontSize: 11, color: C.text2, objectName: `vt-${i}-s` });
  });
  s.addNotes("The honest comparison: AWS already gives you alarms, EventBridge and Systems Manager runbooks, and those are the right tool for a known fix on a known symptom. What they cannot do is read the evidence, cite the documentation, say whether this is a code defect or a sizing problem, and explain it to the engineer who is paged. That is the agentic layer, and it is also what is portable to a cloud where those AWS services do not exist.");
}

// ================================================================== 9 timeline
{
  const s = slide();
  s.addText("One incident, end to end, in under five minutes", { placeholder: "title" });
  s.addText("What it looks like in practice: OpsAgent on an EC2 application killed by the OOM killer", { placeholder: "subtitle" });
  const steps = [
    ["T+0", "Kernel kills the app", "An EC2 application dies to the OOM killer. The alarm fires, the enricher gathers 15 minutes of evidence, the Flow takes it in.", C.accent2],
    ["T+60 s", "L2 is paged", "Triage facts only: service, severity, leak slope, restart count. Nobody waits for the analysis.", C.accent6],
    ["T+3 to 4 min", "Cited root cause and verdict", "RCA with citations, a code-versus-infrastructure verdict naming the file and symbol, and a recommended fix with the exact command, in one Teams card.", C.accent4],
    ["Engineer acts", "Fix applied from the card", "The on-call engineer applies the recommended systemd memory limit; the durable fix goes to the developers as a pull request. Approved automation is phase 2.", C.accent1],
    ["On close", "Knowledge written back", "Incident, fix and outcome are stored with the engineer's accept or reject label, so the next diagnosis starts warmer.", C.accent3],
  ];
  const n = steps.length, gap = 0.22, x0 = 0.6, cw = (W - gap * (n - 1)) / n;
  const lineY = 1.95, cardY = 2.3, cardH = 2.3;
  s.addShape(pres.shapes.LINE, { x: x0 + cw / 2, y: lineY, w: W - cw, h: 0, line: { color: LINE, width: 1.5 }, objectName: "timeline" });
  steps.forEach(([when, head, body, col], i) => {
    const x = x0 + i * (cw + gap);
    s.addShape(pres.shapes.OVAL, { x: x + cw / 2 - 0.11, y: lineY - 0.11, w: 0.22, h: 0.22, fill: { color: col }, line: { color: "FFFFFF", width: 1.5 }, objectName: `node-${i + 1}` });
    card(s, x, cardY, cw, cardH, `tcard-${i + 1}`);
    text(s, when, { x: x + 0.16, y: cardY + 0.14, w: cw - 0.32, h: 0.32, fontSize: 16, bold: true, color: col, objectName: `when-${i + 1}` });
    text(s, head, { x: x + 0.16, y: cardY + 0.5, w: cw - 0.32, h: 0.5, fontSize: 13, bold: true, color: C.text1, objectName: `thead-${i + 1}` });
    text(s, body, { x: x + 0.16, y: cardY + 1.02, w: cw - 0.32, h: cardH - 1.12, fontSize: 11, color: C.text2, objectName: `tbody-${i + 1}` });
  });
  const my = 4.95;
  text(s, "WHAT WE MEASURE", { x: X0, y: my, w: 4, h: 0.26, fontSize: 10, bold: true, color: C.text2, charSpacing: 2, objectName: "measure-label" });
  const tiles = [["under 60 s", "time to first page"], ["under 4 min", "time to cited RCA"], ["% of RCAs", "accepted as correct by L2"], ["cost per incident", "tokens, tools and time, traced end to end"]];
  const tw = (W - gap * 3) / 4;
  tiles.forEach(([big, small], i) => {
    const x = x0 + i * (tw + gap), y = my + 0.34;
    card(s, x, y, tw, 1.15, `tile-${i + 1}`, "FFFFFF", LINE);
    text(s, big, { x: x + 0.18, y: y + 0.16, w: tw - 0.36, h: 0.46, fontSize: 22, bold: true, color: C.accent1, objectName: `tile-${i + 1}-big` });
    text(s, small, { x: x + 0.18, y: y + 0.66, w: tw - 0.36, h: 0.4, fontSize: 11, color: C.text2, objectName: `tile-${i + 1}-small` });
  });
  text(s, "Second use case, CPU throttling, reuses the same flow with a different set of recommended actions.", { x: X0, y: 6.72, w: 12.1, h: 0.26, fontSize: 9.5, italic: true, color: C.text2, objectName: "cpu-note" });
  s.addNotes("Walk the timeline left to right. L2 is paged in a minute with facts, the cited root cause and the recommended fix arrive within four, and the engineer applies it from the card. In phase 2 that fourth step becomes an Approve button. The measures are the four numbers the PoC will report.");
}

// ================================================================== 10 architecture section + arch slide
section("Architecture for the PoC");
sectionSlide("ARCHITECTURE FOR THE POC", "One Flow, five crews in scope, one shared foundation", "CrewAI Flows on Azure OpenAI gpt-4o, fed by native CloudWatch alarms through one small enricher. Read-only everywhere; the agents recommend, people act.")
  .addNotes("Divider into the architecture block.");
{
  const s = slide();
  s.addText("Architecture: from alarm to a recommended fix", { placeholder: "title" });
  s.addText("Five layers: event capture, ingestion, the IncidentFlow and its crews, actions and notifications, shared foundation", { placeholder: "subtitle" });
  card(s, X0, 1.6, 6.3, 5.35, "arch-card2", "FFFFFF", CARD_LINE);
  s.addImage({ path: path.join(__dirname, "arch.png"), x: X0 + 0.15, y: 1.7, w: 6.0, h: 5.15, sizing: { type: "contain", w: 6.0, h: 5.15 }, objectName: "Reference architecture" });
  const rx = 7.25, rw = 5.48;
  const inScope = ["Event capture: CloudWatch agent and alarms (native), EventBridge rule, Lambda enricher", "SQS FIFO intake, de-duplication, persisted Flow state in PostgreSQL", "Triage, Diagnostics, Code Correlation, Incident Bridge and Knowledge crews", "Teams card, email and xMatters page; stage 1 at T+60 s, stage 2 with the RCA", "Knowledge base from systemd, kernel and AWS docs plus closed incidents", "Langfuse tracing, replay evaluation set, cost per incident"];
  const outScope = ["Self-Healing crew executing changes (phase 2, with approval)", "OpenStack adapters beyond stubs (phase 3)", "Kubernetes workloads, autonomous remediation"];
  text(s, "IN THE POC", { x: rx, y: 1.62, w: 3, h: 0.26, fontSize: 10, bold: true, color: C.accent3, charSpacing: 2, objectName: "in-h" });
  text(s, inScope.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < inScope.length - 1 } })), { x: rx, y: 1.92, w: rw, h: 3.0, fontSize: 12, color: C.text2, paraSpaceAfter: 6, objectName: "in-b" });
  text(s, "AFTER THE POC", { x: rx, y: 5.0, w: 3, h: 0.26, fontSize: 10, bold: true, color: C.accent1, charSpacing: 2, objectName: "out-h" });
  text(s, outScope.map((t, j) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: j < outScope.length - 1 } })), { x: rx, y: 5.3, w: rw, h: 1.5, fontSize: 12, color: C.text2, paraSpaceAfter: 6, objectName: "out-b" });
  s.addNotes("The figure is the full reference architecture. Only the first three boxes of the top band exist today, as AWS services. For the PoC, read it without the tinted Self-Healing boxes: everything the agents touch is read-only, and the only outputs are notifications and a knowledge record. The tinted parts are phase 2.");
}

// ================================================================== 11 crew map
{
  const s = slide();
  s.addText("Crews, agents and tools", { placeholder: "title" });
  s.addText("Every agent runs on Azure OpenAI gpt-4o; read-only tools throughout the PoC. The dashed lane is phase 2.", { placeholder: "subtitle" });
  const imgW = 9.45, imgH = imgW * 2016 / 3766;
  card(s, X0, 1.6, imgW + 0.2, imgH + 0.2, "map-card", "FFFFFF", CARD_LINE);
  s.addImage({ path: path.join(__dirname, "crewmap.png"), x: X0 + 0.1, y: 1.7, w: imgW, h: imgH, objectName: "Crew, agent and tool map" });
  const px = 10.55, pw = 2.18;
  const notes = [
    ["Flow band", "Eleven IncidentFlow steps in order. Chip colour is the crew each step invokes; dashed chips are phase 2."],
    ["Agents", "Each lane lists its agents with role and goal. All of them run on the same gpt-4o deployment through CrewAI."],
    ["Tools", "AWS icons mark managed services. A pen marks a write tool; in the PoC only the knowledge base is written."],
    ["Contracts", "Every crew writes one versioned schema and runs under its own IAM role, so permissions follow the crew."],
  ];
  notes.forEach(([h, b], i) => {
    const y = 1.65 + i * 1.28;
    text(s, h, { x: px, y, w: pw, h: 0.28, fontSize: 13, bold: true, color: C.text1, objectName: `note-${i + 1}-h` });
    text(s, b, { x: px, y: y + 0.3, w: pw, h: 0.92, fontSize: 10.5, color: C.text2, objectName: `note-${i + 1}-b` });
  });
  text(s, "Zoom in for detail. The full-size PNG and the editable draw.io file are in the design pack.", { x: X0, y: 6.69, w: 9.65, h: 0.26, fontSize: 9.5, italic: true, color: C.text2, objectName: "map-caption" });
  s.addNotes("The engineering view. Read it top to bottom: the Flow decides what runs and when, each crew owns one stage with its own agents, tools and permissions, and the foundation strip is shared. Self-Healing is drawn dashed because it is phase 2.");
}

// ================================================================== 12 crews at a glance
{
  const s = slide();
  s.addText("Crews at a glance", { placeholder: "title" });
  s.addText("What each crew is for, who works in it, what it is allowed to touch, and what it hands on", { placeholder: "subtitle" });
  const crews = [
    ["T", "Triage", C.accent2, "Event Analyst", "Regex log parser for OOM and systemd lines, EC2 describe and tags, leak slope and restart counter, rule-based classification and severity", "triage-1.0", false],
    ["D", "Diagnostics", C.accent4, "Evidence Correlator, RCA Engineer, Remediation Advisor", "Works from the triage record; AWS Documentation MCP server, knowledge base search, closed-incident lookup", "diagnosis-1.0", false],
    ["C", "Code Correlation", C.accent5, "Repo Navigator, Code Analyst, Ownership Adjudicator", "GitHub MCP server (read-only), shallow clone and grep, 14-day commit history, pattern checks for leaks, N+1 and busy loops", "code-correlation-1.0", false],
    ["B", "Incident Bridge", C.accent6, "Incident Writer, Notifier", "Teams webhook with Adaptive Card, SMTP relay, xMatters trigger API; stage 1 at T+60 s, stage 2 with the RCA", "incident-package-1.0", false],
    ["K", "Knowledge", C.accent3, "KB Curator (weekly), Incident Librarian (on close)", "Docs fetcher for systemd, kernel and OpenStack, client runbooks, chunker and embedder, vector store write, human label capture", "kb-record-1.0", false],
    ["S", "Self-Healing", C.accent1, "Remediation Planner, Change Executor, Verifier", "Allow-listed action catalog, SSM Run Command, EC2 resize, Auto Scaling, Terraform PR generator, health verification. Writes only after approval", "remediation-plan-1.0, remediation-result-1.0", true],
  ];
  const gap = 0.25, cw = (W - 2 * gap) / 3, ch = 2.3, y0 = 1.7;
  crews.forEach(([ini, name, col, agents, tools, writes, p2], i) => {
    const x = X0 + (i % 3) * (cw + gap), y = y0 + Math.floor(i / 3) * (ch + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: ch, rectRadius: 0.08, fill: { color: p2 ? "FFFFFF" : C.background2 }, line: { color: p2 ? HX.accent1 : CARD_LINE, width: p2 ? 1.25 : 0.75, dashType: p2 ? "dash" : "solid" }, objectName: `crew-${i + 1}` });
    badge(s, x + 0.18, y + 0.18, 0.4, ini, col, `crew-${i + 1}-dot`);
    text(s, [{ text: name, options: { bold: true, fontSize: 16, color: C.text1 } }, { text: p2 ? "   phase 2" : "", options: { fontSize: 11, bold: true, color: C.accent1 } }], { x: x + 0.7, y: y + 0.2, w: cw - 0.9, h: 0.36, valign: "middle", objectName: `crew-${i + 1}-name` });
    text(s, [
      { text: "Agents  ", options: { bold: true, color: col } }, { text: agents, options: { color: C.text1, breakLine: true } },
      { text: "Tools  ", options: { bold: true, color: col } }, { text: tools, options: { color: C.text2 } },
    ], { x: x + 0.18, y: y + 0.7, w: cw - 0.36, h: 1.3, fontSize: 10.5, paraSpaceAfter: 4, objectName: `crew-${i + 1}-body` });
    text(s, [{ text: "Writes  ", options: { bold: true, color: col } }, { text: writes, options: { fontFace: "Consolas", color: C.text1 } }],
      { x: x + 0.18, y: y + ch - 0.66, w: cw - 0.36, h: 0.5, fontSize: 10, valign: "bottom", objectName: `crew-${i + 1}-writes` });
  });
  s.addNotes("Use this if the map is too dense for the room. Two things to say out loud: Diagnostics works from the event it is given plus documentation, it does not go back to AWS; and the only write in the PoC is the knowledge record. Self-Healing is listed so the room sees where the roadmap goes.");
}

// ================================================================== 14 future: self-healing
section("Future work");
sectionSlide("FUTURE WORK", "From recommending the fix to applying it", "Phase 2 adds the Self-Healing crew behind an approval gate. Phase 3 carries the same Flow to the OpenStack private cloud.")
  .addNotes("Divider. Two phases beyond the PoC, in order.");
{
  const s = slide();
  s.addText("Phase 2: self-healing with a human in the loop", { placeholder: "title" });
  s.addText("The Self-Healing crew turns the recommended fix into an approved, verified, reversible action", { placeholder: "subtitle" });
  const chain = [
    ["Plan", "pick an allow-listed action, compute parameters, render the exact command as a dry-run", C.accent4],
    ["Approve", "Approve or Reject on the Teams card or xMatters; one action per approval, 30-minute expiry", C.accent1],
    ["Execute", "SSM Run Command or boto3, scoped to the incident's instance and app tag; nothing else", C.accent6],
    ["Verify", "service health, metric back in range, cooldown before any second action", C.accent3],
    ["Roll back", "automatic on a failed verification; every step traced and audited in CloudTrail", C.accent2],
  ];
  const gap = 0.2, cw = (W - 4 * gap) / 5, y0 = 1.72, ch = 1.55;
  chain.forEach(([h, b, col], i) => {
    const x = X0 + i * (cw + gap);
    card(s, x, y0, cw, ch, `sh-${i}`, "FFFFFF", LINE);
    badge(s, x + 0.16, y0 + 0.16, 0.36, String(i + 1), col, `sh-${i}-n`);
    text(s, h, { x: x + 0.62, y: y0 + 0.16, w: cw - 0.8, h: 0.36, fontSize: 14, bold: true, color: C.text1, valign: "middle", objectName: `sh-${i}-h` });
    text(s, b, { x: x + 0.16, y: y0 + 0.62, w: cw - 0.32, h: ch - 0.7, fontSize: 10.5, color: C.text2, objectName: `sh-${i}-b` });
    if (i < chain.length - 1) s.addShape(pres.shapes.LINE, { x: x + cw, y: y0 + ch / 2, w: gap, h: 0, line: { color: "9AA5B1", width: 1.25, endArrowType: "triangle" }, objectName: `sh-${i}-arrow` });
  });
  const rows = [
    ["Action", "Event", "What it does", "Reversal"],
    ["restart_unit", "memory, cpu", "systemctl restart via SSM; skipped if systemd restarted within 10 min", "none needed"],
    ["set_unit_memory_limits", "memory", "MemoryHigh and MemoryMax drop-in on the unit, reload, restart", "remove drop-in, reload"],
    ["add_swap", "memory", "create and enable a swap file", "swapoff, delete file"],
    ["resize_instance", "memory, cpu", "stop, change instance type with headroom rule, start", "resize back after cooldown"],
    ["scale_out_asg", "memory, cpu", "raise desired capacity by one, capped at max", "lower after cooldown"],
    ["set_unit_cpu_quota", "cpu", "CPUQuota drop-in on a noisy unit", "remove drop-in"],
    ["open_terraform_pr", "any", "durable change as a pull request; the agent never applies", "close the PR"],
  ];
  const tableRows = rows.map((r, i) => r.map((c, j) => ({
    text: c,
    options: { bold: i === 0, fontSize: i === 0 ? 10 : 10, fontFace: i > 0 && j === 0 ? "Consolas" : "Calibri", color: i === 0 ? "FFFFFF" : (j === 0 ? HX.dk1 : HX.dk2), fill: { color: i === 0 ? HX.dk2 : (i % 2 ? "FFFFFF" : HX.lt2) }, valign: "middle", margin: [0.04, 0.08, 0.04, 0.08] },
  })));
  s.addTable(tableRows, { x: X0, y: 3.55, w: W, colW: [2.3, 1.5, 5.63, 2.7], rowH: 0.36, border: { type: "solid", pt: 0.5, color: CARD_LINE }, objectName: "catalog-table" });
  text(s, "Allow-listed catalog: the agent chooses only from this list, and only one action per approval. The durable fix always goes through a pull request a person merges.", { x: X0, y: 6.55, w: W, h: 0.4, fontSize: 10.5, italic: true, color: C.text2, objectName: "catalog-note" });
  s.addNotes("Phase 2 is the same Flow with one more crew and one more button. The guardrails are the point: allow-listed actions, dry-run, single-action approvals with expiry, blast-radius check, verification, rollback, and a global kill switch. Terraform stays the system of record; the agent raises the PR, a person applies it.");
}

// ================================================================== 15 future: openstack
{
  const s = slide();
  s.addText("Phase 3: the same Flow on the OpenStack private cloud", { placeholder: "title" });
  s.addText("Three adapters change; the crews, prompts, schemas, knowledge base and approval flow do not", { placeholder: "subtitle" });
  const rows = [
    ["Concern", "AWS proof of concept", "OpenStack equivalent", "Adapter"],
    ["Metrics and alarms", "CloudWatch agent, alarms, EventBridge", "Prometheus node_exporter and Alertmanager, or Aodh", "SignalSource"],
    ["Logs", "CloudWatch Logs", "Loki or ELK", "SignalSource"],
    ["Event transport", "SQS FIFO", "RabbitMQ", "Ingestion"],
    ["Instance operations", "boto3 EC2, instance type change", "openstacksdk Nova; resize is a cold migration, check flavor quota", "InstanceAPI"],
    ["Commands on the host", "SSM Run Command", "Ansible through a bastion", "HostExec"],
    ["Scaling", "Auto Scaling group", "Senlin or Heat", "InstanceAPI"],
    ["Secrets and audit", "Secrets Manager, CloudTrail", "Barbican or Vault, CADF audit", "Foundation"],
  ];
  const tableRows = rows.map((r, i) => r.map((c, j) => ({
    text: c,
    options: { bold: i === 0 || j === 0, fontSize: 11, fontFace: i > 0 && j === 3 ? "Consolas" : "Calibri", color: i === 0 ? "FFFFFF" : (j === 0 ? HX.dk1 : HX.dk2), fill: { color: i === 0 ? HX.dk2 : (j === 3 ? "FFF0EF" : (i % 2 ? "FFFFFF" : HX.lt2)) }, valign: "middle", margin: [0.05, 0.1, 0.05, 0.1] },
  })));
  s.addTable(tableRows, { x: X0, y: 1.72, w: 8.3, colW: [1.75, 2.35, 2.9, 1.3], rowH: 0.46, border: { type: "solid", pt: 0.5, color: CARD_LINE }, objectName: "os-table" });
  const rx = 9.2, rw = 3.53;
  card(s, rx, 1.72, rw, 3.65, "os-card");
  text(s, "UNCHANGED", { x: rx + 0.22, y: 1.9, w: 3, h: 0.26, fontSize: 10, bold: true, color: C.accent3, charSpacing: 2, objectName: "os-h" });
  const same = ["The six crews and their prompts", "All nine versioned schemas; provider field flips to openstack", "Knowledge base and citations", "Two-stage paging and the approval flow", "Tracing, evaluation set, cost per incident"];
  text(s, same.map((t, j) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: j < same.length - 1 } })), { x: rx + 0.22, y: 2.22, w: rw - 0.44, h: 3.0, fontSize: 11.5, color: C.text2, paraSpaceAfter: 6, objectName: "os-b" });
  text(s, "The Alertmanager SignalSource stub is small enough to show beside the AWS path, so a later demo can end with one Flow handling a CloudWatch event and an Alertmanager event back to back.", { x: rx, y: 5.55, w: rw, h: 1.2, fontSize: 11, italic: true, color: C.text2, objectName: "os-note" });
  s.addNotes("The portability argument in one table. Only the left-hand column of the pipeline changes. Two honest differences: a Nova resize is slower than an EC2 type change and needs flavor quota, and memory metrics come from node_exporter, which must already be deployed.");
}

// ================================================================== 16 asks and next steps
section("Asks and next steps");
{
  const s = slide();
  s.addText("Asks and next steps", { placeholder: "title" });
  s.addText("What we need to start, and what happens after this meeting", { placeholder: "subtitle" });
  const asks = [
    ["Environment", "An AWS account with a demo instance where we can install the CloudWatch agent, alarms and the enricher, or an archive of past alarms and logs to replay from"],
    ["Pain points", "The top three incident types by volume and by time to resolve, to prioritise after memory and CPU"],
    ["Teams and xMatters", "A channel with an incoming webhook, and an xMatters tenant or a stand-in for the voice page"],
    ["Repository access", "Read-only access to the demo application repository for Code Correlation"],
    ["Approvers", "Who signs off on a recommended fix, and later on the phase 2 action catalog"],
    ["Model access", "Azure OpenAI gpt-4o is available; confirm an embeddings deployment or accept a local model"],
  ];
  const next = [
    ["Agree the scope", "Confirm the PoC scope and the four measures: time to first page, time to cited RCA, RCAs accepted by L2, cost per incident"],
    ["Open the doors", "Access in place, demo instance alarmed, first raw event captured and archived for replay"],
    ["Show the PoC", "Alarm to a cited root cause and a recommended fix on a Teams card, from a replayed event"],
    ["Decide what is next", "Go or no-go on phase 2 self-healing and the OpenStack track"],
  ];
  const gap = 0.3, lw = 7.4, rw = W - lw - gap;
  card(s, X0, 1.72, lw, 5.05, "asks-card");
  text(s, "ASKS", { x: X0 + 0.25, y: 1.9, w: 3, h: 0.26, fontSize: 10, bold: true, color: C.accent1, charSpacing: 2, objectName: "asks-h" });
  asks.forEach(([k, v], j) => {
    const y = 2.25 + j * 0.74;
    text(s, [{ text: k, options: { bold: true, color: C.text1, breakLine: true } }, { text: v, options: { color: C.text2 } }], { x: X0 + 0.25, y, w: lw - 0.5, h: 0.7, fontSize: 12, objectName: `ask-${j}` });
  });
  const rx = X0 + lw + gap;
  card(s, rx, 1.72, rw, 5.05, "next-card", "FFFFFF", LINE);
  text(s, "NEXT STEPS", { x: rx + 0.25, y: 1.9, w: 3, h: 0.26, fontSize: 10, bold: true, color: C.accent2, charSpacing: 2, objectName: "next-h" });
  next.forEach(([k, v], j) => {
    const y = 2.3 + j * 1.1;
    badge(s, rx + 0.25, y, 0.4, String(j + 1), C.accent2, `next-${j}-n`);
    text(s, [{ text: k, options: { bold: true, color: C.text1, breakLine: true } }, { text: v, options: { color: C.text2 } }], { x: rx + 0.8, y, w: rw - 1.05, h: 1.0, fontSize: 12, objectName: `next-${j}` });
  });
  s.addNotes("Close on the asks. The environment and the replay archive are the two that gate the PoC build; everything else can land as we go.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
