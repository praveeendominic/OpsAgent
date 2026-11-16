"""Shared helpers for crews: one LLM, one way to run a crew and harvest its typed output and token usage."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from opsagent.config import get_settings
from opsagent.llm import make_llm
from opsagent.tracing import usage_from_crew_output

T = TypeVar("T", bound=BaseModel)


def agent_defaults() -> dict[str, Any]:
    s = get_settings()
    return dict(llm=make_llm(), verbose=False, max_iter=s.crew_max_iter, max_execution_time=s.crew_max_execution_time,
                allow_delegation=False, respect_context_window=True)


@dataclass
class CrewRun:
    output: BaseModel | None
    usage: dict[str, int]
    raw: str
    error: str | None = None


def run_crew(crew, inputs: dict[str, Any], model: type[T]) -> CrewRun:
    """Kick off a crew synchronously and coerce the final task output into `model`.

    Never raises: a failure is returned in `error` so the Flow can degrade gracefully."""
    try:
        result = crew.kickoff(inputs=inputs)
    except Exception as exc:  # noqa: BLE001
        return CrewRun(output=None, usage={}, raw="", error=f"{type(exc).__name__}: {exc}")
    usage = usage_from_crew_output(result)
    raw = getattr(result, "raw", "") or ""
    typed = getattr(result, "pydantic", None)
    if isinstance(typed, model):
        return CrewRun(output=typed, usage=usage, raw=raw)
    # second chance: the model may have emitted JSON without the structured path
    data = getattr(result, "json_dict", None)
    if not data and raw:
        data = _extract_json(raw)
    if data:
        try:
            return CrewRun(output=model.model_validate(data), usage=usage, raw=raw)
        except Exception as exc:  # noqa: BLE001
            return CrewRun(output=None, usage=usage, raw=raw, error=f"output did not match {model.__name__}: {exc}")
    return CrewRun(output=None, usage=usage, raw=raw, error=f"no structured output for {model.__name__}")


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def as_prompt_json(obj: BaseModel | dict | list, max_chars: int = 12000) -> str:
    """Compact JSON for prompts, wrapped as data so log content is never read as instructions."""
    if isinstance(obj, BaseModel):
        text = obj.model_dump_json(exclude_none=True)
    else:
        text = json.dumps(obj, default=str, ensure_ascii=False)
    if len(text) > max_chars:
        text = text[:max_chars] + " ...(truncated)"
    return text
