# OpsAgent design deliverables

Technical design document (living, comment-enabled):
https://claude.ai/artifact/A878pEGhmHrPPkwMkfGUbj

Files in this folder:

| File | What it is | How to open |
| --- | --- | --- |
| `OpsAgent-Technical-Design.docx` | Word export of the design document: cover, contents, 15 numbered sections, 4 figures (architecture and sequence embedded as SVG with PNG fallback) | Word 2016 or later, LibreOffice, Google Docs |
| `opsagent-architecture.drawio` | Editable draw.io file, 4 pages: 1. Architecture (AWS PoC), 2. CrewAI IncidentFlow, 3. Sequence alarm to knowledge write-back, 4. OpenStack adapter mapping | https://app.diagrams.net, File, Open from, Device; or the draw.io desktop app, or the VS Code "Draw.io Integration" extension |
| `opsagent-architecture.svg` | Standalone architecture diagram for slides and PDFs | Any browser, PowerPoint (Insert, Pictures), Google Slides |
| `opsagent-sequence.svg` | Standalone sequence diagram with target times for the demo OOM incident | Same |
| `opsagent-incident-flow-crewai.png` | The IncidentFlow as drawn by CrewAI's built-in `Flow.plot()` (crewai 1.12.2): red = `@start`, red outline = `@router`, dashed red = router path, solid red = `and_` join, black = `listen` | Any image viewer; drop into slides |
| `flow-plot/` | The interactive HTML that `Flow.plot()` produced (`opsagent_incident_flow.html` plus its CSS and JS) and `opsagent_flow_plot.py`, the structural stub Flow that generated it | Open the HTML in a browser (hover a node for triggers and router paths; theme toggle bottom-left). Regenerate with `python opsagent_flow_plot.py .` from inside `flow-plot/` |
| `opsagent-crew-agent-tool-map.drawio` | Crew, agent and tool map: IncidentFlow step band, one swimlane per crew with its agents (role, goal), its tools (AWS icons for managed services, pen mark for write tools), the schema it writes and its IAM role; shared foundation strip; legend and title block | https://app.diagrams.net, File, Open from, Device |
| `opsagent-crew-agent-tool-map.png` | 2x PNG export of the map, white background, for slides | Any image viewer |
| `OpsAgent-PoC-Deck.pptx` | The client deck, 17 slides, white background, 16:9: cover, agenda, background, observation and gap, the proposed event capture path, point of view (agents investigate, people approve; what agentic automation changes; one incident end to end), architecture for the PoC (reference architecture with scope, crew map, crews at a glance), future work (phase 2 self-healing with approval, phase 3 OpenStack), asks and next steps. Speaker notes on every slide | PowerPoint; built by `generators/ppt/deck.js` with pptxgenjs |
| `generators/` | `gen_diagrams.py` (architecture, flow, sequence, OpenStack pages and the two SVGs) and `gen_crew_map.py` (crew map); `ppt/deck.js` builds the client deck (run with NODE_PATH pointing at a folder holding pptxgenjs 3.12). Run `python -I generators/gen_diagrams.py .` or `python -I generators/gen_crew_map.py opsagent-crew-agent-tool-map.drawio` from this folder | Python 3, no dependencies |

Export to PNG or PDF from draw.io with File, Export as. The SVGs embed no fonts and no external resources.

Regenerate after edits to the shared data (band contents, flow nodes, message list, crew tables) with the scripts in `generators/`; each file set is produced from one script so geometry and labels stay consistent.
