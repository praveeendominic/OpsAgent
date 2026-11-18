"""MLflow tracing: one trace per incident. The root span is the incident, every RunRecorder step is a child span, and
MLflow's CrewAI autolog hangs the crew, task, agent, tool and LLM spans under the step that ran them.

Off unless OPSAGENT_MLFLOW=1. Tracing never breaks a run: any MLflow failure is logged and the Flow carries on."""
from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from opsagent.config import get_settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_configured_uri: str | None = None  # tracking URI autolog was set up for; "" after a failed setup


def setup() -> bool:
    """Point MLflow at the tracking store and switch on the CrewAI autolog. Idempotent; False when tracing is off."""
    global _configured_uri
    s = get_settings()
    if not s.mlflow_tracing:
        return False
    with _lock:
        if _configured_uri != s.mlflow_uri:
            try:
                s.export_llm_env()
                import mlflow
                import mlflow.crewai

                mlflow.set_tracking_uri(s.mlflow_uri)
                mlflow.set_experiment(s.mlflow_experiment)
                mlflow.crewai.autolog(silent=True)
                _configured_uri = s.mlflow_uri
            except Exception as exc:  # noqa: BLE001
                log.warning("MLflow tracing disabled: %s: %s", type(exc).__name__, exc)
                _configured_uri = ""
                return False
    return bool(_configured_uri)


class IncidentTrace:
    """Handle on the root span of one incident; every method is a no-op when tracing is off."""

    def __init__(self, span: Any = None):
        self.span = span

    @property
    def trace_id(self) -> str | None:
        return getattr(self.span, "trace_id", None)

    def describe(self) -> dict[str, str] | None:
        if self.span is None:
            return None
        s = get_settings()
        return {"trace_id": self.trace_id, "tracking_uri": s.mlflow_uri, "experiment": s.mlflow_experiment}

    def finish(self, outputs: Any = None, tags: dict[str, Any] | None = None) -> None:
        """Call inside the trace, once the Flow has returned: the run summary becomes the trace's response."""
        if self.span is None:
            return
        try:
            import mlflow

            if outputs is not None:
                self.span.set_outputs(outputs)
            if tags:
                mlflow.update_current_trace(tags={k: str(v) for k, v in tags.items() if v is not None})
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow trace not finalised: %s", exc)


@contextmanager
def incident_trace(incident_id: str, event: Any = None) -> Iterator[IncidentTrace]:
    """Open the root span for an incident. Everything run inside the block lands in the same trace."""
    if not setup():
        yield IncidentTrace()
        return
    import mlflow

    tags = {"incident_id": incident_id, "brand": get_settings().brand}
    for field in ("event_id", "instance_id", "event_type"):
        value = getattr(event, field, None)
        if value:
            tags[field] = str(value)
    with mlflow.start_span(name=f"incident {incident_id}", span_type="CHAIN") as span:
        try:
            span.set_inputs(tags)
            mlflow.update_current_trace(tags=tags)
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow trace not tagged: %s", exc)
        yield IncidentTrace(span)


def instrument_llm(llm: Any) -> None:
    """Give the LLM's class a traced `call`. MLflow's autolog patches crewai.LLM.call only, and CrewAI's native
    providers (AzureCompletion for the azure/ route) override it, so without this a trace has no LLM spans."""
    if not _configured_uri:
        return
    cls = type(llm)
    call = cls.__dict__.get("call")
    if call is None or getattr(call, "_opsagent_traced", False):
        return  # inherited from crewai.LLM (autolog has it) or already wrapped

    @functools.wraps(call)
    def traced(self, messages, *args, **kwargs):
        import mlflow

        if not _configured_uri or mlflow.get_current_active_span() is None:
            return call(self, messages, *args, **kwargs)
        before = dict(getattr(self, "_token_usage", None) or {})
        with mlflow.start_span(name=f"{cls.__name__}.call", span_type="CHAT_MODEL") as span:
            model = str(getattr(self, "model", "")).split("/")[-1]
            _quiet(span.set_inputs, {"messages": messages} | {k: v for k, v in kwargs.items() if k in ("tools", "response_model") and v})
            _quiet(span.set_attributes, {"mlflow.llm.model": model, "mlflow.llm.provider": "azure"})
            result = call(self, messages, *args, **kwargs)
            after = getattr(self, "_token_usage", None) or {}
            used = {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in ("prompt_tokens", "completion_tokens")}
            _quiet(span.set_attribute, "mlflow.chat.tokenUsage", {
                "input_tokens": used["prompt_tokens"], "output_tokens": used["completion_tokens"],
                "total_tokens": used["prompt_tokens"] + used["completion_tokens"]})
            _quiet(span.set_outputs, result)
            return result

    traced._opsagent_traced = True
    cls.call = traced


def _quiet(fn: Any, *args: Any) -> None:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        log.debug("MLflow span not annotated: %s", exc)


def open_span(name: str, kind: str = "flow", crew: str | None = None, inputs: Any = None,
              root: IncidentTrace | None = None) -> Any:
    """Start a step span under the active span (or the incident root) and make it current for this thread, so the
    crew spans of the step nest under it. Returns a handle for close_span, or None when nothing is traced."""
    if not _configured_uri:
        return None
    try:
        import mlflow
        from mlflow.tracing import provider

        parent = mlflow.get_current_active_span() or (root.span if root else None)
        if parent is None:
            return None
        attributes = {"opsagent.kind": kind} | ({"opsagent.crew": crew} if crew else {})
        span = mlflow.start_span_no_context(name=name, span_type="AGENT" if kind == "crew" else "CHAIN",
                                            parent_span=parent, inputs=inputs, attributes=attributes)
        return span, provider.set_span_in_context(span)
    except Exception as exc:  # noqa: BLE001
        log.warning("MLflow span %s not opened: %s", name, exc)
        return None


def close_span(handle: Any, output: Any = None, usage: dict | None = None, cost_usd: float | None = None,
               error: str | None = None) -> None:
    if handle is None:
        return
    span, token = handle
    try:
        from mlflow.tracing import provider

        provider.detach_span_from_context(token)
    except Exception:  # noqa: BLE001  (closed from another thread: the context there is gone anyway)
        pass
    try:
        attributes: dict[str, Any] = {}
        if usage:
            attributes["opsagent.usage"] = usage
            attributes["opsagent.cost_usd"] = cost_usd or 0.0
        if error:
            attributes["opsagent.error"] = error
        span.end(outputs=output, attributes=attributes or None, status="ERROR" if error else "OK")
    except Exception as exc:  # noqa: BLE001
        log.warning("MLflow span not closed: %s", exc)
