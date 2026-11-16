"""Chunk the curated markdown docs and load them into the "docs" namespace.

Chunk ids are ``<source_id>#<slug>-<n>``; the citation ``source`` is ``kb://<source_id>#<slug>`` so a Citation can
point at a section regardless of how many size-chunks the section was split into.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from opsagent.config import PACKAGE_ROOT

log = logging.getLogger(__name__)

DOCS_DIR = PACKAGE_ROOT / "kb" / "docs"
DOCS_NAMESPACE = "docs"

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TOKENS_PER_WORD = 1.3


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def approx_tokens(text: str) -> int:
    return int(len(text.split()) * _TOKENS_PER_WORD)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return (front matter dict, body). Front matter is simple ``key: value`` lines."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[m.end():]


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split on ``##`` headings. Text before the first heading becomes an 'overview' section."""
    sections: list[tuple[str, str]] = []
    matches = list(_H2.finditer(body))
    preamble = body[: matches[0].start()].strip() if matches else body.strip()
    if preamble:
        sections.append(("Overview", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[m.end():end].strip()
        if content:
            sections.append((m.group(1).strip(), content))
    return sections


def _split_by_size(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Split paragraph-wise, falling back to word windows with overlap for oversized paragraphs."""
    if approx_tokens(text) <= max_tokens:
        return [text]
    max_words = max(1, int(max_tokens / _TOKENS_PER_WORD))
    overlap_words = max(0, min(int(overlap / _TOKENS_PER_WORD), max_words // 2))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        words = len(para.split())
        if words > max_words:
            if current:
                pieces.append("\n\n".join(current))
                current, current_words = [], 0
            tokens = para.split()
            start = 0
            while start < len(tokens):
                pieces.append(" ".join(tokens[start:start + max_words]))
                if start + max_words >= len(tokens):
                    break
                start += max_words - overlap_words
            continue
        if current and current_words + words > max_words:
            pieces.append("\n\n".join(current))
            # carry the tail of the previous piece as overlap
            tail = " ".join(" ".join(current).split()[-overlap_words:]) if overlap_words else ""
            current = [tail, para] if tail else [para]
            current_words = len(tail.split()) + words
        else:
            current.append(para)
            current_words += words
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def chunk_markdown(
    text: str,
    source_id: str,
    url: str | None,
    title: str,
    max_tokens: int = 600,
    overlap: int = 80,
) -> list[dict[str, Any]]:
    """Return chunks as dicts with keys id, source, title, url, text, section, source_id, chunk_index."""
    _, body = parse_front_matter(text)
    chunks: list[dict[str, Any]] = []
    seen_slugs: dict[str, int] = {}
    for section_title, content in _split_sections(body):
        slug = slugify(section_title)
        # keep anchors unique if two sections share a name
        if slug in seen_slugs:
            seen_slugs[slug] += 1
            slug = f"{slug}-{seen_slugs[slug]}"
        else:
            seen_slugs[slug] = 0
        pieces = _split_by_size(content, max_tokens=max_tokens, overlap=overlap)
        for n, piece in enumerate(pieces):
            chunk_text = f"{title}: {section_title}\n\n{piece}"
            chunks.append(
                {
                    "id": f"{source_id}#{slug}-{n}",
                    "source": f"kb://{source_id}#{slug}",
                    "title": f"{title}: {section_title}",
                    "url": url,
                    "text": chunk_text,
                    "section": section_title,
                    "source_id": source_id,
                    "chunk_index": n,
                }
            )
    return chunks


def chunk_file(path: Path, max_tokens: int = 600, overlap: int = 80) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    meta, _ = parse_front_matter(text)
    source_id = meta.get("source_id") or path.stem
    title = meta.get("title") or path.stem.replace("-", " ")
    url = meta.get("url") or None
    return chunk_markdown(text, source_id=source_id, url=url, title=title, max_tokens=max_tokens, overlap=overlap)


def build_docs_index(docs_dir: Path | None = None, store=None) -> int:
    """Clear the docs namespace and ingest every ``*.md`` under ``docs_dir``. Returns the chunk count."""
    from opsagent.kb.store import get_store

    store = store or get_store()
    docs_dir = Path(docs_dir) if docs_dir else DOCS_DIR
    files = sorted(docs_dir.glob("*.md"))
    all_chunks: list[dict[str, Any]] = []
    for path in files:
        chunks = chunk_file(path)
        log.info("kb ingest %s -> %d chunks", path.name, len(chunks))
        all_chunks.extend(chunks)

    store.clear(DOCS_NAMESPACE)
    if not all_chunks:
        return 0
    ids = [c["id"] for c in all_chunks]
    texts = [c["text"] for c in all_chunks]
    metadatas = [
        {
            "title": c["title"],
            "source": c["source"],
            "url": c["url"],
            "section": c["section"],
            "source_id": c["source_id"],
            "chunk_index": c["chunk_index"],
        }
        for c in all_chunks
    ]
    return store.add(DOCS_NAMESPACE, ids, texts, metadatas)
