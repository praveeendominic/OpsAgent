# OpsAgent

Agentic L1/L2 incident response on CrewAI Flows. One `IncidentFlow` takes a `raw-1.0` alarm event and runs five
crews: Triage (deterministic parse plus one short LLM pass), Diagnostics (cited root cause from a local knowledge
base), Code Correlation (reads the application repository and issues a code / infra / shared verdict), Incident
Bridge (two-stage page to Teams, email and a ServiceNow incident) and Knowledge (writes the closed incident back with a human label).
Self-Healing is phase 2 and is not part of this proof of concept.

Design pack: `docs/` (design document, deck, draw.io and SVG diagrams, generators).

## Quick start

```bash
# Python 3.12+ with crewai 1.12 already installed; from the project root
python -m pip install -e .            # installs the opsagent package (editable)
copy .env.example .env                # then fill AZURE_API_KEY and, optionally, Teams, SMTP and ServiceNow
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
  HTML). These are always written; Teams, SMTP and ServiceNow are used in addition when configured in `.env`.
- `.opsagent/`: the FAISS knowledge base, the incident registry (de-duplication) and the Flow persistence database.

The four measures printed at the end of a run: time to stage 1, time to stage 2, total tokens, cost per incident.

## Layout

```
events/                 sample raw-1.0 event (the message the enricher puts on the queue)
config/instances.yaml   demo inventory (instance type, memory, tags) and app -> repository map
config/severity.yaml    severity policy: triage thresholds, ordered severity rules, ServiceNow impact/urgency, paging
examples/orders-api/    sample FastAPI service with the unbounded order cache the agents find
src/opsagent/
  schemas/              versioned contracts: raw-1.0, triage-1.0, diagnosis-1.0, code-correlation-1.0,
                        incident-package-1.0, kb-record-1.0 (and the phase 2 remediation models)
  parsing/              deterministic parsers, classification rules, inventory lookup, triage builder
  kb/                   FAISS store, document ingestion, closed incidents, curated docs
  tools/                CrewAI tools: knowledge base search, closed incidents, repository tools
  crews/                triage, diagnostics, code_correlation, incident_bridge, knowledge (YAML configs)
  notify/               Adaptive Cards, Teams webhook, SMTP email, ServiceNow Table API, xMatters paging, outbox
  flow/                 IncidentFlow, state, incident ids and de-duplication
  ui/                   Streamlit run recorder
  tracing.py            run recorder (run.json), token and cost accounting
tests/                  offline unit tests and an offline end-to-end Flow test
```

## ServiceNow

With `SERVICENOW_INSTANCE` plus `SERVICENOW_USER`/`SERVICENOW_PASSWORD` (or `SERVICENOW_TOKEN`) in `.env`, the Incident
Bridge drives one ServiceNow incident per OpsAgent incident through the Table API (`/api/now/table/incident`):

| Flow step | ServiceNow action | Fields |
|---|---|---|
| `page_stage1` | POST creates the record | short_description, description (stage 1 card as text), impact/urgency from severity (critical = 1/1), category, `correlation_id` = OpsAgent incident id, `correlation_display` = OpsAgent, contact_type = monitoring, optional assignment_group and caller_id |
| `page_stage2` | PATCH adds a work note | the stage 2 card as text: RCA, citations, code verdict, immediate and durable fix |
| watchdog | PATCH adds a work note | "diagnosis still running" delay notice |
| `close` | PATCH adds a work note | knowledge-record digest and the label workflow; with `SERVICENOW_RESOLVE_ON_CLOSE=1` the record is also set to Resolved |

Stage 2, the delay notice and the closure find the record by `correlation_id`, so nothing has to be kept between
steps and a stage 2 that arrives without a stage 1 record still opens one. Every call becomes a `servicenow` receipt
(`created INC0010042 (priority 1)`, `updated INC0010042: work note added`, or the HTTP error) with the record URL as
target; credentials never appear in receipts or outbox files. `SERVICENOW_INSTANCE` accepts the subdomain
(`dev12345`), the host or the full URL. A free Personal Developer Instance from developer.servicenow.com is enough for
the demo; the integration user needs the `itil` role.

## xMatters

With `XMATTERS_TRIGGER_URL` in `.env` the Incident Bridge pages on-call through xMatters. The quickest trigger is the
stock **Send Alert** form every instance ships with, through the xM API:
`https://<company>.xmatters.com/api/xm/1/forms/<form id>/triggers` (form id from `GET /api/xm/1/forms`), with
`XMATTERS_PROPERTIES=summary=Summary,details=Message` because that form's layout carries only those two properties.
Any Flow Designer workflow works as well: an **HTTP trigger** whose flow has a *Create Event* step, or the inbound
integration URL of a **Create Event** form whose layout defines the payload properties below (then leave
`XMATTERS_PROPERTIES` empty). All of this exists on the free xMatters plan; on-call groups are created under Groups
and xMatters handles the escalation (for example L1 Support first, L2 Support after five minutes).

| Flow step | xMatters action | Content |
|---|---|---|
| `page_stage1` | POST the trigger URL, which raises the event and pages the recipients | `properties`: incident_id, event_id, stage, severity, service, instance_id, summary, details (stage 1 card as text), brand, trace_url; `priority` HIGH / MEDIUM / LOW from the severity policy (`xmatters:` block); `recipients` from `XMATTERS_RECIPIENTS` (group or user names, or uuids, sent in the `id` field: a form trigger silently drops recipients given as `targetName`) |
| `page_stage2` | POST an annotation on the event | the stage 2 card as text: RCA, citations, code verdict, fixes |
| watchdog | POST an annotation | "diagnosis still running" delay notice |
| `close` | POST an annotation, then terminate the event (`XMATTERS_TERMINATE_ON_CLOSE=1`, the default) | knowledge-record digest and the label workflow |

The trigger answers with a `requestId`; the sender keeps it in `outbox/<incident>/xmatters.json` and resolves it to
the event through `GET /api/xm/1/events?requestId=...` when stage 2 arrives. Annotations and termination need the
xM API, so `XMATTERS_USER` / `XMATTERS_PASSWORD` must be a user with the *REST Web Service User* role (the user name
is the web login, usually the email address) or an API key id and secret (both are basic auth). Without them the
trigger still pages at stage 1 when it is a Flow Designer URL; stage 2 and the delay notice then
raise a follow-up event carrying the same `incident_id` and a `stage` property, and the closure reports that it could
not annotate. Receipts read `event requested (requestId ..., priority HIGH)`, `annotated event 1234: diagnosis added`
or `annotated and terminated event 1234`; the trigger URL's apiKey, if any, never appears in a receipt.

## Tests

```bash
python -m pytest -q                   # offline suite (parsers, kb, tools, notify, ui, flow with canned crews)
python -m opsagent run --event events/log_event.json   # live functional run against Azure OpenAI
```

## Configuration

All settings come from `.env` (see `.env.example`). Nothing in the repository contains credentials; `.env`,
`outbox/`, `runs/` and `.opsagent/` are ignored by git.

### Severity policy (`config/severity.yaml`)

Severity is decided deterministically in the Triage step; the LLM only comments on it. The thresholds and the
mappings are policy, so they live in a versioned YAML file an operator can change in a pull request, not in code
and not in `.env` (only the path is a setting: `OPSAGENT_SEVERITY_POLICY`, default `config/severity.yaml`).

```yaml
rules:                      # evaluated in order, first match wins
  - severity: critical
    when: oom_event
  - severity: critical
    when: restart_count_at_least
    value: 2
  - severity: critical
    when: mem_available_pct_below
    value: 5
  - severity: warning
    when: classification_confidence_in
    value: [high, medium]
default: info
classification:             # thresholds behind the memory / rapid_growth classification rule
  rapid_growth_min_slope_mb_per_min: 50
  rapid_growth_max_mem_available_pct: 10
servicenow:                 # severity -> impact, urgency; the instance derives priority from the pair
  critical: {impact: 1, urgency: 1}
  warning:  {impact: 2, urgency: 2}
  info:     {impact: 3, urgency: 3}
xmatters:                   # severity -> priority of the xMatters event
  critical: HIGH
  warning: MEDIUM
  info: LOW
paging:                     # severities that page stage 1 immediately and run the diagnosis crews
  immediate: [critical]
```

Rule kinds are a closed set in code (`oom_event`, `restart_count_at_least`, `mem_available_pct_below`,
`leak_slope_at_least`, `classification_confidence_in`, `alarm_event_type_in`); new conditions are added as code
with tests, the file only chooses order, thresholds and outcome. The file is validated strictly: an unknown rule
kind, a missing threshold or a misspelt severity stops the run at load time instead of silently downgrading an
OOM kill. A missing file means the built-in defaults, which equal the shipped file. Edits are picked up on the
next run without a restart, and every `run.json` records the policy path, its digest, the rule order in force and
the rule that produced the severity (`severity_policy` and the `triage.parse` step).
