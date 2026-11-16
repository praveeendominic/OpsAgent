"""Local knowledge base: curated documentation chunks and closed incidents in FAISS."""
from __future__ import annotations

from opsagent.kb.store import FaissStore, SearchHit, get_store


def warm_up() -> FaissStore:
    """Load the embedding model and existing indexes once, from the main thread, before parallel crews start."""
    return get_store().warm_up()


__all__ = ["FaissStore", "SearchHit", "get_store", "warm_up"]
