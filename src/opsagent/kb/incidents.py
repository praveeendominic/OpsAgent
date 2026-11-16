"""Closed incidents: a JSON file per incident under ``<kb_path>/incidents/`` plus an embedding in the
"incidents" namespace so the Diagnostics crew can find similar past cases."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, get_args

from opsagent.config import get_settings
from opsagent.kb.store import FaissStore, SearchHit, get_store
from opsagent.schemas.kb import KBRecord, Label

log = logging.getLogger(__name__)

INCIDENTS_NAMESPACE = "incidents"
VALID_LABELS: tuple[str, ...] = get_args(Label)


def incidents_dir() -> Path:
    d = get_settings().kb_path / "incidents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _incident_path(incident_id: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in incident_id)
    return incidents_dir() / f"{safe}.json"


def _metadata(record: KBRecord) -> dict:
    return {
        "title": f"Closed incident {record.incident_id}: {record.digest}",
        "source": f"kb://incidents/{record.incident_id}",
        "url": None,
        "label": record.label,
        "service": record.service,
        "event_type": record.event_type,
        "severity": record.severity,
        "verdict": record.verdict,
        "root_cause_category": record.root_cause_category,
        "created_at": record.created_at.isoformat(),
    }


def store_incident(record: KBRecord, store: FaissStore | None = None) -> Path:
    """Write the record to disk and upsert its embedding. Returns the JSON path."""
    store = store or get_store()
    path = _incident_path(record.incident_id)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    store.add(INCIDENTS_NAMESPACE, [record.incident_id], [record.embedding_text()], [_metadata(record)])
    log.info("kb stored incident %s (label=%s)", record.incident_id, record.label)
    return path


def load_incident(incident_id: str) -> KBRecord | None:
    path = _incident_path(incident_id)
    if not path.exists():
        return None
    return KBRecord.model_validate_json(path.read_text(encoding="utf-8"))


def list_incidents() -> list[KBRecord]:
    records = []
    for p in sorted(incidents_dir().glob("*.json")):
        try:
            records.append(KBRecord.model_validate_json(p.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not hide the others
            log.warning("kb: skipping unreadable incident file %s: %s", p.name, exc)
    return records


def label_incident(incident_id: str, label: str, by: str, store: FaissStore | None = None) -> KBRecord:
    """Set the human label, then re-store and re-embed (the label is part of the embedding text)."""
    if label not in VALID_LABELS:
        raise ValueError(f"invalid label {label!r}; expected one of {', '.join(VALID_LABELS)}")
    record = load_incident(incident_id)
    if record is None:
        raise FileNotFoundError(f"no stored incident with id {incident_id!r}")
    record = record.model_copy(update={"label": label, "labelled_by": by, "labelled_at": datetime.now(timezone.utc)})
    store_incident(record, store=store)
    return record


def search_incidents(
    query: str,
    k: int = 3,
    exclude_labels: Iterable[str] = ("wrong",),
    store: FaissStore | None = None,
) -> list[SearchHit]:
    """Nearest closed incidents, dropping any whose label is in ``exclude_labels``."""
    store = store or get_store()
    excluded = set(exclude_labels or ())
    total = store.count(INCIDENTS_NAMESPACE)
    if total == 0 or k <= 0:
        return []
    # over-fetch so filtering does not leave us short
    hits = store.search(query, k=min(total, k + len(excluded) * 3 + 3), namespace=INCIDENTS_NAMESPACE)
    kept = [h for h in hits if h.metadata.get("label") not in excluded]
    return kept[:k]
