"""One place that builds the CrewAI LLM for every agent (Azure OpenAI through LiteLLM)."""
from __future__ import annotations

from crewai import LLM

from opsagent.config import get_settings


def make_llm(temperature: float | None = None, max_tokens: int | None = None) -> LLM:
    """A fresh LLM per call. CrewAI attaches its token-counting callbacks to the LLM object, so agents must not share
    one instance or usage is attributed to the wrong crew."""
    s = get_settings()
    s.export_llm_env()
    kwargs = dict(
        model=f"azure/{s.azure_deployment}",
        api_key=s.azure_api_key or None,
        base_url=s.azure_resource_base or None,
        api_version=s.azure_api_version or None,
        temperature=s.llm_temperature if temperature is None else temperature,
    )
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return LLM(**kwargs)


def smoke_test() -> str:
    """One cheap call to prove the deployment answers. Returns the model's reply."""
    llm = make_llm(temperature=0.0, max_tokens=20)
    return str(llm.call("Reply with the single word OK."))
