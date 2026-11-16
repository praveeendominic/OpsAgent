"""Knowledge-base tools for the Diagnostics crew.

Both tools return a compact text block. Each hit is rendered as ``[n] title | source | score`` followed by the
chunk text, so the agent can copy ``source`` verbatim into a Citation.
"""
from __future__ import annotations

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from opsagent.kb.store import SearchHit

MAX_TEXT_CHARS = 700


def format_hits(hits: list[SearchHit], max_chars: int = MAX_TEXT_CHARS) -> str:
    blocks: list[str] = []
    for n, hit in enumerate(hits, start=1):
        text = " ".join(hit.text.split())
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        header = f"[{n}] {hit.title} | {hit.source} | {hit.score:.3f}"
        if hit.url:
            header += f" | {hit.url}"
        blocks.append(f"{header}\n{text}")
    return "\n\n".join(blocks)


class KBSearchArgs(BaseModel):
    query: str = Field(description="What you need to know, phrased as a question or a short description of the symptom.")
    k: int = Field(default=5, ge=1, le=20, description="How many passages to return.")


class KBSearchTool(BaseTool):
    name: str = "knowledge_base_search"
    description: str = (
        "Search the curated operations knowledge base (systemd, Linux memory/OOM, cgroups, EC2, CloudWatch). "
        "Returns numbered passages as '[n] title | source | score' followed by the text. "
        "Cite a passage by copying its source (kb://...) exactly."
    )
    args_schema: Type[BaseModel] = KBSearchArgs

    def _run(self, query: str, k: int = 5) -> str:
        from opsagent.kb.store import get_store

        hits = get_store().search(query, k=k, namespace="docs")
        if not hits:
            return "No matching passages in the knowledge base."
        return format_hits(hits)


class ClosedIncidentsArgs(BaseModel):
    query: str = Field(description="Symptom, service or root-cause description to match against closed incidents.")
    k: int = Field(default=3, ge=1, le=10, description="How many incidents to return.")


class ClosedIncidentsTool(BaseTool):
    name: str = "closed_incidents_search"
    description: str = (
        "Find previously closed incidents similar to the current one, with their root cause, verdict and fixes. "
        "Incidents a human labelled as wrong are excluded. Cite by the source (kb://incidents/<id>)."
    )
    args_schema: Type[BaseModel] = ClosedIncidentsArgs

    def _run(self, query: str, k: int = 3) -> str:
        from opsagent.kb.incidents import search_incidents

        hits = search_incidents(query, k=k)
        if not hits:
            return "No similar closed incidents."
        return format_hits(hits)
