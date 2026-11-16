"""Offline tests for the local knowledge base. Loads the local embedding model once; uses a tmp store so the
real .opsagent/kb directory is never touched."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from opsagent.kb import ingest as kb_ingest
from opsagent.kb import incidents as kb_incidents
from opsagent.kb import store as kb_store
from opsagent.kb.ingest import DOCS_DIR, build_docs_index, chunk_markdown
from opsagent.kb.incidents import label_incident, load_incident, search_incidents, store_incident
from opsagent.kb.store import FaissStore
from opsagent.schemas.kb import KBRecord
from opsagent.tools.kb_search import ClosedIncidentsTool, KBSearchTool

MODEL = "BAAI/bge-small-en-v1.5"

SAMPLE_MD = """---
title: Sample Doc
source_id: sample/doc
url: https://example.invalid/sample
---

Intro paragraph before any heading.

## First Section

Short body for the first section.

## Second Section!

""" + " ".join(f"word{i}" for i in range(1200)) + "\n"


@pytest.fixture(scope="session")
def embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL)


@pytest.fixture
def kb_env(tmp_path: Path, monkeypatch, embedding_model):
    """Point settings and the store singleton at tmp_path; share the already-loaded model."""
    from opsagent import config

    monkeypatch.setenv("OPSAGENT_STATE_DIR", str(tmp_path / "state"))
    config.get_settings.cache_clear()
    kb_store.get_store.cache_clear()
    store = kb_store.get_store()
    store._model = embedding_model
    assert store.root.is_relative_to(tmp_path)
    yield store
    config.get_settings.cache_clear()
    kb_store.get_store.cache_clear()


def _record(incident_id: str, **overrides) -> KBRecord:
    base = dict(
        incident_id=incident_id,
        event_id=f"evt-{incident_id}",
        event_type="memory",
        service="orders-api",
        severity="critical",
        digest="orders-api killed by the OOM killer after memory climbed to 97 percent",
        root_cause_summary="Unbounded in-process cache in the order lookup path grew until the kernel killed the service.",
        root_cause_category="application_memory_leak",
        verdict="code_defect",
        code_location="orders/cache.py",
        immediate_fix="Add MemoryHigh/MemoryMax drop-in to the systemd unit and restart.",
        durable_fix="Bound the cache with an LRU and a TTL.",
        created_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return KBRecord(**base)


# ---------------------------------------------------------------------------- chunking
def test_chunk_markdown_ids_and_sources_have_anchors():
    chunks = chunk_markdown(SAMPLE_MD, source_id="sample/doc", url="https://example.invalid/sample",
                            title="Sample Doc", max_tokens=300, overlap=40)
    ids = [c["id"] for c in chunks]
    assert "sample/doc#overview-0" in ids
    assert "sample/doc#first-section-0" in ids
    second = [c for c in chunks if c["source"] == "kb://sample/doc#second-section"]
    assert len(second) >= 2, "oversized section must be split by size"
    assert [c["id"] for c in second] == [f"sample/doc#second-section-{n}" for n in range(len(second))]
    for c in chunks:
        assert c["source"].startswith("kb://sample/doc#")
        assert c["url"] == "https://example.invalid/sample"
        assert c["title"].startswith("Sample Doc: ")
        assert c["id"].startswith(c["source"][len("kb://"):] + "-")
    # overlap: the tail of one piece appears at the head of the next
    tail = " ".join(second[0]["text"].split()[-5:])
    assert tail in second[1]["text"]


def test_package_docs_have_front_matter():
    files = sorted(DOCS_DIR.glob("*.md"))
    assert len(files) == 6
    for f in files:
        meta, _ = kb_ingest.parse_front_matter(f.read_text(encoding="utf-8"))
        assert {"title", "source_id", "url"} <= set(meta), f.name
        assert meta["url"].startswith("https://"), f.name


# ---------------------------------------------------------------------------- store
def test_store_upsert_delete_count_and_reload(tmp_path: Path, embedding_model):
    store = FaissStore(tmp_path / "idx", MODEL)
    store._model = embedding_model
    assert store.count("t") == 0
    store.add("t", ["a", "b"], ["alpha text", "beta text"], [{"title": "A", "source": "kb://t#a"}, {}])
    assert store.count("t") == 2
    store.add("t", ["a"], ["alpha replaced"], [{"title": "A2", "source": "kb://t#a"}])
    assert store.count("t") == 2
    hit = store.get("t", "a")
    assert hit is not None and hit.text == "alpha replaced" and hit.title == "A2"
    assert store.delete("t", ["b"]) == 1
    assert store.count("t") == 1

    reloaded = FaissStore(tmp_path / "idx", MODEL)
    reloaded._model = embedding_model
    assert reloaded.count("t") == 1
    hits = reloaded.search("alpha", k=5, namespace="t")
    assert [h.id for h in hits] == ["a"]
    assert hits[0].source == "kb://t#a"
    reloaded.clear("t")
    assert reloaded.count("t") == 0
    assert reloaded.search("alpha", namespace="t") == []


# ---------------------------------------------------------------------------- docs index + search
def test_build_docs_index_and_search(kb_env: FaissStore):
    n = build_docs_index()
    assert n > 10
    assert kb_env.count("docs") == n

    query = "service killed by the oom killer set a memory limit on the systemd unit"
    hits = kb_env.search(query, k=5, namespace="docs")
    assert len(hits) == 5
    assert any(("MemoryHigh" in h.text or "MemoryMax" in h.text) for h in hits[:3]), [h.source for h in hits]
    for h in hits:
        assert h.source.startswith("kb://")
        assert "#" in h.source
        assert h.url and h.url.startswith("https://")
        assert 0.0 < h.score <= 1.0001

    # warm search timing (model already loaded)
    kb_env.search(query, k=5)
    t0 = time.perf_counter()
    for _ in range(5):
        kb_env.search(query, k=5)
    per_search_ms = (time.perf_counter() - t0) / 5 * 1000
    print(f"\nwarm docs search: {per_search_ms:.1f} ms over {n} chunks")
    assert per_search_ms < 2000


# ---------------------------------------------------------------------------- incidents
def test_store_and_search_incidents_round_trip(kb_env: FaissStore):
    rec = _record("INC-1001")
    path = store_incident(rec)
    assert path.exists() and path.is_relative_to(kb_env.root.parent)
    loaded = load_incident("INC-1001")
    assert loaded is not None and loaded.incident_id == "INC-1001" and loaded.label == "pending"
    assert load_incident("INC-does-not-exist") is None

    hits = search_incidents("orders service out of memory, cache leak", k=3)
    assert hits and hits[0].id == "INC-1001"
    assert hits[0].source == "kb://incidents/INC-1001"
    assert hits[0].metadata["service"] == "orders-api"
    assert hits[0].metadata["verdict"] == "code_defect"


def test_label_wrong_excludes_from_search(kb_env: FaissStore):
    store_incident(_record("INC-2001"))
    store_incident(_record("INC-2002", service="payments-api", digest="payments-api OOM killed, same pattern"))
    assert {h.id for h in search_incidents("OOM killed api", k=5)} == {"INC-2001", "INC-2002"}

    updated = label_incident("INC-2001", "wrong", by="reviewer")
    assert updated.label == "wrong" and updated.labelled_by == "reviewer" and updated.labelled_at is not None
    assert load_incident("INC-2001").label == "wrong"
    assert kb_env.count("incidents") == 2  # re-embedded in place, not duplicated

    ids = {h.id for h in search_incidents("OOM killed api", k=5)}
    assert "INC-2001" not in ids and "INC-2002" in ids
    # explicitly asking for everything brings it back
    assert "INC-2001" in {h.id for h in search_incidents("OOM killed api", k=5, exclude_labels=())}

    accepted = label_incident("INC-2002", "accepted", by="reviewer")
    assert accepted.label == "accepted"


def test_invalid_label_raises(kb_env: FaissStore):
    store_incident(_record("INC-3001"))
    with pytest.raises(ValueError):
        label_incident("INC-3001", "bogus", by="reviewer")
    with pytest.raises(FileNotFoundError):
        label_incident("INC-missing", "accepted", by="reviewer")


# ---------------------------------------------------------------------------- tools
def test_kb_search_tool_output(kb_env: FaissStore):
    build_docs_index()
    tool = KBSearchTool()
    assert tool.name == "knowledge_base_search"
    out = tool._run(query="MemoryHigh MemoryMax systemd drop-in", k=3)
    assert "kb://" in out
    assert out.startswith("[1] ")
    assert out.count("\n\n") == 2  # three blocks
    assert "https://www.freedesktop.org" in out


def test_closed_incidents_tool_output(kb_env: FaissStore):
    tool = ClosedIncidentsTool()
    assert tool.name == "closed_incidents_search"
    assert tool._run(query="anything") == "No similar closed incidents."
    store_incident(_record("INC-4001"))
    out = tool._run(query="orders api oom", k=3)
    assert "kb://incidents/INC-4001" in out and out.startswith("[1] ")
