"""FAISS-backed vector store with one namespace per sub-directory.

Layout under ``root/<namespace>/``:

* ``index.faiss`` - ``IndexFlatIP`` over L2-normalised vectors (inner product == cosine similarity)
* ``vectors.npy`` - the same vectors, kept so rebuilds after delete/upsert do not re-embed
* ``meta.jsonl``  - one JSON object per row, in index order: ``{"id", "text", "metadata"}``

The scale here is small (hundreds of chunks), so a delete or upsert simply rebuilds the flat index from the
cached vectors that survive.
"""
from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_INDEX_FILE = "index.faiss"
_VECTORS_FILE = "vectors.npy"
_META_FILE = "meta.jsonl"


class SearchHit(BaseModel):
    id: str
    namespace: str
    title: str
    source: str = Field(description="stable citation key, e.g. kb://systemd/resource-control#memoryhigh")
    url: str | None = None
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class _Namespace:
    """In-memory view of one namespace; persisted by FaissStore.save()."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.metadatas: list[dict[str, Any]] = []
        self.vectors: np.ndarray | None = None  # (n, dim) float32, L2-normalised
        self.index = None  # faiss.IndexFlatIP, built lazily from vectors
        self.dirty = False

    # ---------------------------------------------------------------- persistence
    def load(self) -> None:
        meta = self.path / _META_FILE
        vecs = self.path / _VECTORS_FILE
        if not (meta.exists() and vecs.exists()):
            return
        rows = [json.loads(line) for line in meta.read_text(encoding="utf-8").splitlines() if line.strip()]
        vectors = np.load(vecs).astype(np.float32)
        if len(rows) != vectors.shape[0]:
            log.warning("kb namespace %s: meta rows (%d) != vectors (%d); ignoring on-disk data",
                        self.path.name, len(rows), vectors.shape[0])
            return
        self.ids = [r["id"] for r in rows]
        self.texts = [r["text"] for r in rows]
        self.metadatas = [r.get("metadata", {}) for r in rows]
        self.vectors = vectors if vectors.shape[0] else None
        self.index = None
        self.dirty = False

    def save(self) -> None:
        import faiss

        self.path.mkdir(parents=True, exist_ok=True)
        with (self.path / _META_FILE).open("w", encoding="utf-8") as fh:
            for i, t, m in zip(self.ids, self.texts, self.metadatas):
                fh.write(json.dumps({"id": i, "text": t, "metadata": m}, ensure_ascii=False) + "\n")
        if self.vectors is not None and self.vectors.shape[0]:
            np.save(self.path / _VECTORS_FILE, self.vectors)
            faiss.write_index(self._ensure_index(), str(self.path / _INDEX_FILE))
        else:
            for name in (_VECTORS_FILE, _INDEX_FILE):
                p = self.path / name
                if p.exists():
                    p.unlink()
        self.dirty = False

    # ---------------------------------------------------------------- mutation
    def _ensure_index(self):
        import faiss

        if self.index is None:
            if self.vectors is None or not self.vectors.shape[0]:
                return None
            self.index = faiss.IndexFlatIP(int(self.vectors.shape[1]))
            self.index.add(self.vectors)
        return self.index

    def remove(self, ids: set[str]) -> int:
        keep = [i for i, _id in enumerate(self.ids) if _id not in ids]
        removed = len(self.ids) - len(keep)
        if removed == 0:
            return 0
        self.ids = [self.ids[i] for i in keep]
        self.texts = [self.texts[i] for i in keep]
        self.metadatas = [self.metadatas[i] for i in keep]
        self.vectors = self.vectors[keep] if (self.vectors is not None and keep) else None
        self.index = None
        self.dirty = True
        return removed

    def append(self, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]], vectors: np.ndarray) -> None:
        self.ids.extend(ids)
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)
        self.vectors = vectors if self.vectors is None else np.vstack([self.vectors, vectors])
        self.index = None
        self.dirty = True

    def clear(self) -> None:
        self.ids, self.texts, self.metadatas = [], [], []
        self.vectors = None
        self.index = None
        self.dirty = True

    def __len__(self) -> int:
        return len(self.ids)


class FaissStore:
    """Cosine-similarity vector store; one FAISS index + one meta.jsonl per namespace under ``root``."""

    def __init__(self, root: Path, model_name: str) -> None:
        self.root = Path(root)
        self.model_name = model_name
        self.root.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._lock = threading.RLock()
        self._namespaces: dict[str, _Namespace] = {}
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and (child / _META_FILE).exists():
                self._ns(child.name)

    # ---------------------------------------------------------------- embedding
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            log.info("loading embedding model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vecs = self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        return np.ascontiguousarray(vecs, dtype=np.float32)

    # ---------------------------------------------------------------- namespaces
    def _ns(self, namespace: str) -> _Namespace:
        ns = self._namespaces.get(namespace)
        if ns is None:
            ns = _Namespace(self.root / namespace)
            ns.load()
            self._namespaces[namespace] = ns
        return ns

    def namespaces(self) -> list[str]:
        return sorted(self._namespaces)

    # ---------------------------------------------------------------- public API
    def add(self, namespace: str, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> int:
        """Upsert: existing ids are replaced. Returns the number of records written."""
        if not (len(ids) == len(texts)):
            raise ValueError("ids and texts must have the same length")
        metadatas = metadatas or [{} for _ in ids]
        if len(metadatas) != len(ids):
            raise ValueError("metadatas must have the same length as ids")
        if not ids:
            return 0
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate ids in a single add() call")
        vectors = self.embed(texts)
        with self._lock:
            ns = self._ns(namespace)
            ns.remove(set(ids))
            ns.append(list(ids), list(texts), [dict(m) for m in metadatas], vectors)
            ns.save()
        return len(ids)

    def delete(self, namespace: str, ids: list[str]) -> int:
        with self._lock:
            ns = self._ns(namespace)
            removed = ns.remove(set(ids))
            if removed:
                ns.save()
            return removed

    def search(self, query: str, k: int = 5, namespace: str = "docs") -> list[SearchHit]:
        with self._lock:
            ns = self._ns(namespace)
            index = ns._ensure_index()
            if index is None or k <= 0:
                return []
            q = self.embed([query])
            k_eff = min(k, len(ns))
            scores, idxs = index.search(q, k_eff)
            hits: list[SearchHit] = []
            for score, i in zip(scores[0].tolist(), idxs[0].tolist()):
                if i < 0:
                    continue
                meta = ns.metadatas[i]
                hits.append(
                    SearchHit(
                        id=ns.ids[i],
                        namespace=namespace,
                        title=str(meta.get("title") or ns.ids[i]),
                        source=str(meta.get("source") or f"kb://{namespace}/{ns.ids[i]}"),
                        url=meta.get("url"),
                        text=ns.texts[i],
                        score=float(score),
                        metadata=meta,
                    )
                )
            return hits

    def get(self, namespace: str, id: str) -> SearchHit | None:
        with self._lock:
            ns = self._ns(namespace)
            try:
                i = ns.ids.index(id)
            except ValueError:
                return None
            meta = ns.metadatas[i]
            return SearchHit(
                id=id, namespace=namespace, title=str(meta.get("title") or id),
                source=str(meta.get("source") or f"kb://{namespace}/{id}"), url=meta.get("url"),
                text=ns.texts[i], score=1.0, metadata=meta,
            )

    def count(self, namespace: str) -> int:
        with self._lock:
            return len(self._ns(namespace))

    def clear(self, namespace: str) -> None:
        with self._lock:
            ns = self._ns(namespace)
            ns.clear()
            ns.save()

    def save(self) -> None:
        with self._lock:
            for ns in self._namespaces.values():
                if ns.dirty:
                    ns.save()


@lru_cache(maxsize=1)
def get_store() -> FaissStore:
    from opsagent.config import get_settings

    s = get_settings()
    return FaissStore(root=s.kb_path / "index", model_name=s.embedding_model)
