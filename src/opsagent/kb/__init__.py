"""Local knowledge base: curated documentation chunks and closed incidents in FAISS."""
from __future__ import annotations

from opsagent.kb.store import FaissStore, SearchHit, get_store

__all__ = ["FaissStore", "SearchHit", "get_store"]
