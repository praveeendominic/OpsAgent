# OpsAgent

Agentic L1/L2 incident response on CrewAI Flows. One `IncidentFlow` takes a `raw-1.0` alarm event and runs five
crews: Triage (deterministic parse plus one short LLM pass), Diagnostics (cited root cause from a local knowledge
base), Code Correlation (reads the application repository and issues a code / infra / shared verdict), Incident
Bridge (two-stage page to Teams and email) and Knowledge (writes the closed incident back with a human label).
Self-Healing is phase 2 and is not part of this proof of concept.

Design pack: `docs/` (design document, deck, draw.io and SVG diagrams, generators).

## Quick start

```bash
# Python 3.12+ with crewai 1.12 already installed; from the project root
python -m pip install -e .            # installs the opsagent package (editable)
copy .env.example .env                # then fill AZURE_API_KEY and, optionally, Teams and SMTP
python -m opsagent smoke              # one call to the Azure OpenAI deployment
python -m opsagent kb build           # embeds the bundled docs into the FAISS knowledge base
python -m opsagent run --event events/log_event.json
python -m opsagent ui                 # Streamlit run recorder on http://localhost:8501
```

`python -m opsagent --help` lists every command: `run`, `runs`, `smoke`, `plot`, `ui`, `kb build`, `kb search`,
`kb label`.

## What a run produces

- `runs/<incident_id>/run.json`: every step with timings, token usage and cost, plus every artifact
  (`triage`, `diagnosis`, `code_correlation`, `package_stage1`, `package_stage2`, `kb_record`).
- `outbox/<incident_id>/`: the stage 1 and stage 2 Adaptive Cards (JSON, HTML, Markdown) and the emails (`.eml`,
  HTML). These are always written; Teams and SMTP are used in addition when configured in `.env`.
- `.opsagent/`: the FAISS knowledge base, the incident registry (de-duplication) and the Flow persistence database.

The four measures printed at the end of a run: time to stage 1, time to stage 2, total tokens, cost per incident.

## Layout

```
events/                 sample raw-1.0 event (the message the enricher puts on the queue)
config/instances.yaml   demo inventory (instance type, memory, tags) and app -> repository map
examples/orders-api/    sample FastAPI service with the unbounded order cache the agents find
src/opsagent/
  schemas/              versioned contracts: raw-1.0, triage-1.0, diagnosis-1.0, code-correlation-1.0,
                        incident-package-1.0, kb-record-1.0 (and the phase 2 remediation models)
  parsing/              deterministic parsers, classification rules, inventory lookup, triage builder
  kb/                   FAISS store, document ingestion, closed incidents, curated docs
  tools/                CrewAI tools: knowledge base search, closed incidents, repository tools
  crews/                triage, diagnostics, code_correlation, incident_bridge, knowledge (YAML configs)
  notify/               Adaptive Cards, Teams webhook, SMTP email, outbox
  flow/                 IncidentFlow, state, incident ids and de-duplication
  ui/                   Streamlit run recorder
  tracing.py            run recorder (run.json), token and cost accounting
tests/                  offline unit tests and an offline end-to-end Flow test
```

## Tests

```bash
python -m pytest -q                   # offline suite (parsers, kb, tools, notify, ui, flow with canned crews)
python -m opsagent run --event events/log_event.json   # live functional run against Azure OpenAI
```

## Configuration

All settings come from `.env` (see `.env.example`). Nothing in the repository contains credentials; `.env`,
`outbox/`, `runs/` and `.opsagent/` are ignored by git.
