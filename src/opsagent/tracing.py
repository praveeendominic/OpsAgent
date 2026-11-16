"""Run recorder: every Flow run writes runs/<incident_id>/run.json with each step, its timing, token usage and
cost, plus the JSON of every artifact. The Streamlit app and the CLI read this file; nothing else is needed to
replay a demo."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from opsagent.config import get_settings

# gpt-4o list prices (USD per 1M tokens) used for the cost estimate when LiteLLM gives none
PRICES = {"gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return json.loads(obj.model_dump_json())
    if isinstance(obj, (list, tuple)):
        return [_jsonable(o) for o in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str | None = None) -> float:
    model = (model or get_settings().azure_deployment).lower()
    for name, (pin, pout) in PRICES.items():
        if name in model:
            return round(prompt_tokens * pin / 1e6 + completion_tokens * pout / 1e6, 6)
    return 0.0


def usage_from_crew_output(output: Any) -> dict[str, int]:
    """Pull token counts from a CrewOutput (crewai >= 1.x exposes token_usage as UsageMetrics)."""
    usage = getattr(output, "token_usage", None)
    if usage is None:
        return {}
    get = lambda k: int(getattr(usage, k, 0) or (usage.get(k, 0) if isinstance(usage, dict) else 0))  # noqa: E731
    return {
        "prompt_tokens": get("prompt_tokens"),
        "completion_tokens": get("completion_tokens"),
        "total_tokens": get("total_tokens"),
        "successful_requests": get("successful_requests"),
    }


class RunRecorder:
    """Thread-safe JSON recorder. Create one per Flow run; call start_step/end_step around every step."""

    def __init__(self, incident_id: str, event_id: str = "", run_dir: Path | None = None):
        s = get_settings()
        self.incident_id = incident_id
        self.dir = run_dir or (s.runs_path / incident_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "run.json"
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        self.data: dict[str, Any] = {
            "incident_id": incident_id,
            "event_id": event_id,
            "brand": s.brand,
            "model": f"azure/{s.azure_deployment}",
            "started_at": _now(),
            "finished_at": None,
            "status": "running",
            "steps": [],
            "artifacts": {},
            "receipts": [],
            "timings": {},
            "totals": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "llm_calls": 0},
            "errors": [],
        }
        self._open: dict[str, dict[str, Any]] = {}
        self.flush()

    # ------------------------------------------------------------------ steps
    def elapsed(self) -> float:
        return round(time.perf_counter() - self._t0, 3)

    def start_step(self, name: str, kind: str = "flow", crew: str | None = None, inputs: Any = None) -> None:
        with self._lock:
            step = {
                "name": name, "kind": kind, "crew": crew, "status": "running",
                "started_at": _now(), "t_start": self.elapsed(), "ended_at": None, "t_end": None,
                "duration_s": None, "inputs": _jsonable(inputs) if inputs is not None else None,
                "output": None, "usage": {}, "cost_usd": 0.0, "error": None,
            }
            self._open[name] = step
            self.data["steps"].append(step)
            self.flush()

    def end_step(self, name: str, output: Any = None, usage: dict | None = None, error: str | None = None) -> None:
        with self._lock:
            step = self._open.pop(name, None)
            if step is None:
                step = {"name": name, "kind": "flow", "started_at": _now(), "t_start": self.elapsed()}
                self.data["steps"].append(step)
            step["ended_at"] = _now()
            step["t_end"] = self.elapsed()
            step["duration_s"] = round(step["t_end"] - step["t_start"], 3)
            step["status"] = "error" if error else "done"
            step["error"] = error
            if output is not None:
                step["output"] = _jsonable(output)
            if usage:
                step["usage"] = usage
                cost = estimate_cost(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                step["cost_usd"] = cost
                t = self.data["totals"]
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    t[k] += int(usage.get(k, 0))
                t["cost_usd"] = round(t["cost_usd"] + cost, 6)
                t["llm_calls"] += int(usage.get("successful_requests", 0))
            if error:
                self.data["errors"].append({"step": name, "error": error, "at": _now()})
            self.flush()

    # ------------------------------------------------------------------ artifacts and milestones
    def artifact(self, name: str, obj: Any) -> Path:
        """Store an artifact both inside run.json and as its own file next to it."""
        payload = _jsonable(obj)
        with self._lock:
            self.data["artifacts"][name] = payload
            p = self.dir / f"{name}.json"
            p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            self.flush()
        return p

    def milestone(self, name: str, seconds: float | None = None) -> float:
        value = round(self.elapsed() if seconds is None else seconds, 3)
        with self._lock:
            self.data["timings"][name] = value
            self.flush()
        return value

    def receipt(self, receipt: Any) -> None:
        with self._lock:
            self.data["receipts"].append(_jsonable(receipt))
            self.flush()

    def finish(self, status: str = "done") -> None:
        with self._lock:
            self.data["status"] = status
            self.data["finished_at"] = _now()
            self.data["duration_s"] = self.elapsed()
            self.flush()

    def flush(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(self.path)


def list_runs(runs_dir: Path | None = None) -> list[dict[str, Any]]:
    runs_dir = runs_dir or get_settings().runs_path
    out = []
    for p in sorted(runs_dir.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_run(incident_id: str, runs_dir: Path | None = None) -> dict[str, Any] | None:
    p = (runs_dir or get_settings().runs_path) / incident_id / "run.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
