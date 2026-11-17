"""Severity policy (config/severity.yaml): the thresholds and mappings behind the deterministic triage rules.

The rule *kinds* are code (a closed enum, each with tests). The file chooses their order, their thresholds and the
severity each one yields, the classification thresholds, the ServiceNow impact/urgency per severity and which
severities page stage 1 immediately. Validation is strict: an unknown rule kind, a missing threshold or a typo in a
severity name fails when the policy is loaded instead of silently downgrading an OOM kill to info.

Policy is operator-reviewed configuration, not a secret, so it lives in a versioned YAML file rather than in .env.
Only the file path is a setting (OPSAGENT_SEVERITY_POLICY). The LLM never sees or influences any of this.
"""
from __future__ import annotations

import hashlib
import threading
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opsagent.config import get_settings
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Classification, Evidence, Severity

SEVERITIES: tuple[Severity, ...] = ("critical", "warning", "info")
BUILT_IN_SOURCE = "built-in defaults"


class SeverityPolicyError(ValueError):
    """The policy file exists but is not a valid policy. Raised at load time; the flow must not start on it."""


class RuleKind(StrEnum):
    OOM_EVENT = "oom_event"  # a kernel OOM kill was parsed from the system log
    RESTART_COUNT_AT_LEAST = "restart_count_at_least"  # systemd restart counter >= value
    MEM_AVAILABLE_PCT_BELOW = "mem_available_pct_below"  # memory available at the kill < value (percent)
    LEAK_SLOPE_AT_LEAST = "leak_slope_at_least"  # RSS growth >= value (MB per minute)
    CLASSIFICATION_CONFIDENCE_IN = "classification_confidence_in"  # rule-based classification confidence in value
    ALARM_EVENT_TYPE_IN = "alarm_event_type_in"  # the alarm's event_type (memory, cpu, disk, ...) in value


_NUMERIC_KINDS = {RuleKind.RESTART_COUNT_AT_LEAST, RuleKind.MEM_AVAILABLE_PCT_BELOW, RuleKind.LEAK_SLOPE_AT_LEAST}
_LIST_KINDS = {RuleKind.CLASSIFICATION_CONFIDENCE_IN, RuleKind.ALARM_EVENT_TYPE_IN}


class SeverityRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    when: RuleKind
    value: float | list[str] | None = None

    @model_validator(mode="after")
    def _value_matches_kind(self) -> "SeverityRule":
        if self.when in _NUMERIC_KINDS:
            if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
                raise ValueError(f"rule '{self.when}' needs a numeric value")
        elif self.when in _LIST_KINDS:
            if not isinstance(self.value, list) or not self.value or not all(isinstance(v, str) for v in self.value):
                raise ValueError(f"rule '{self.when}' needs a non-empty list of strings as value")
            self.value = [v.strip().lower() for v in self.value]
        elif self.value is not None:
            raise ValueError(f"rule '{self.when}' takes no value")
        return self

    def matches(self, event: RawEvent, evidence: Evidence, classification: Classification) -> bool:
        lp = evidence.leak_profile
        if self.when is RuleKind.OOM_EVENT:
            return bool(evidence.oom_events)
        if self.when is RuleKind.RESTART_COUNT_AT_LEAST:
            return evidence.restart_count is not None and evidence.restart_count >= self.value  # type: ignore[operator]
        if self.when is RuleKind.MEM_AVAILABLE_PCT_BELOW:
            return lp is not None and lp.mem_available_pct_at_kill is not None and lp.mem_available_pct_at_kill < self.value  # type: ignore[operator]
        if self.when is RuleKind.LEAK_SLOPE_AT_LEAST:
            return lp is not None and lp.slope_mb_per_min >= self.value  # type: ignore[operator]
        if self.when is RuleKind.CLASSIFICATION_CONFIDENCE_IN:
            return classification.confidence in self.value  # type: ignore[operator]
        if self.when is RuleKind.ALARM_EVENT_TYPE_IN:
            return (event.event_type or "unknown").lower() in self.value  # type: ignore[operator]
        return False

    def describe(self) -> str:
        if self.value is None:
            return f"{self.when} -> {self.severity}"
        return f"{self.when} {self.value} -> {self.severity}"


class ClassificationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rapid_growth_min_slope_mb_per_min: float = Field(default=50.0, gt=0)
    rapid_growth_max_mem_available_pct: float = Field(default=10.0, ge=0, le=100)


class TicketPriority(BaseModel):
    """ServiceNow derives priority from impact x urgency (1 = high, 3 = low); OpsAgent never writes priority itself."""

    model_config = ConfigDict(extra="forbid")

    impact: int = Field(ge=1, le=3)
    urgency: int = Field(ge=1, le=3)


XmPriority = Literal["HIGH", "MEDIUM", "LOW"]


class PagingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    immediate: list[Severity] = Field(default_factory=lambda: ["critical"])


_DEFAULT_TICKET: dict[str, TicketPriority] = {
    "critical": TicketPriority(impact=1, urgency=1),
    "warning": TicketPriority(impact=2, urgency=2),
    "info": TicketPriority(impact=3, urgency=3),
}
_DEFAULT_XMATTERS: dict[str, str] = {"critical": "HIGH", "warning": "MEDIUM", "info": "LOW"}


class SeverityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[SeverityRule] = Field(min_length=1)
    default: Severity = "info"
    classification: ClassificationThresholds = Field(default_factory=ClassificationThresholds)
    servicenow: dict[Severity, TicketPriority] = Field(default_factory=lambda: dict(_DEFAULT_TICKET))
    xmatters: dict[Severity, XmPriority] = Field(default_factory=lambda: dict(_DEFAULT_XMATTERS))  # type: ignore[arg-type]
    paging: PagingPolicy = Field(default_factory=PagingPolicy)

    # provenance, filled by the loader; excluded from dumps so a dumped policy re-validates
    source: str = Field(default=BUILT_IN_SOURCE, exclude=True)
    digest: str = Field(default="", exclude=True)

    @model_validator(mode="after")
    def _complete_ticket_map(self) -> "SeverityPolicy":
        for sev in SEVERITIES:
            self.servicenow.setdefault(sev, _DEFAULT_TICKET[sev])
            self.xmatters.setdefault(sev, _DEFAULT_XMATTERS[sev])  # type: ignore[arg-type]
        return self

    # ------------------------------------------------------------------ decisions
    def severity_for(self, event: RawEvent, evidence: Evidence, classification: Classification) -> Severity:
        """First matching rule wins; `default` when none matches."""
        for rule in self.rules:
            if rule.matches(event, evidence, classification):
                return rule.severity
        return self.default

    def matched_rule(self, event: RawEvent, evidence: Evidence, classification: Classification) -> str:
        for rule in self.rules:
            if rule.matches(event, evidence, classification):
                return rule.describe()
        return f"default -> {self.default}"

    def pages(self, severity: str) -> bool:
        return severity in self.paging.immediate

    def ticket_priority(self, severity: str) -> tuple[str, str]:
        """(impact, urgency) as the Table API strings for a severity; unknown severities get the info mapping."""
        tp = self.servicenow.get(severity) or self.servicenow["info"]  # type: ignore[call-overload]
        return str(tp.impact), str(tp.urgency)

    def event_priority(self, severity: str) -> str:
        """xMatters event priority (HIGH / MEDIUM / LOW) for a severity; unknown severities get the info mapping."""
        return str(self.xmatters.get(severity) or self.xmatters["info"])  # type: ignore[call-overload]

    def describe(self) -> dict[str, Any]:
        """Compact provenance for run.json: which file, which digest, and the rule order that was in force."""
        return {
            "source": self.source,
            "digest": self.digest,
            "rules": [r.describe() for r in self.rules],
            "default": self.default,
            "classification": self.classification.model_dump(),
            "servicenow": {k: f"impact {v.impact} / urgency {v.urgency}" for k, v in self.servicenow.items()},
            "xmatters": dict(self.xmatters),
            "paging_immediate": list(self.paging.immediate),
        }


def default_policy() -> SeverityPolicy:
    """The behaviour the rules had before they became configurable; also what config/severity.yaml ships with."""
    return SeverityPolicy(
        rules=[
            SeverityRule(severity="critical", when=RuleKind.OOM_EVENT),
            SeverityRule(severity="critical", when=RuleKind.RESTART_COUNT_AT_LEAST, value=2),
            SeverityRule(severity="critical", when=RuleKind.MEM_AVAILABLE_PCT_BELOW, value=5),
            SeverityRule(severity="warning", when=RuleKind.CLASSIFICATION_CONFIDENCE_IN, value=["high", "medium"]),
        ],
        default="info",
    )


# ---------------------------------------------------------------------------------------------------- loading
def load_policy(path: Path) -> SeverityPolicy:
    """Load and validate a policy file. A missing file yields the built-in defaults; a bad file raises."""
    path = Path(path)
    if not path.exists():
        return default_policy()
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise SeverityPolicyError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise SeverityPolicyError(f"{path}: the policy must be a mapping with a 'rules' list")
    try:
        policy = SeverityPolicy.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise SeverityPolicyError(f"{path}: {problems}") from exc
    policy.source = str(path)
    policy.digest = hashlib.sha256(raw).hexdigest()[:12]
    return policy


_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, SeverityPolicy]] = {}


def get_policy() -> SeverityPolicy:
    """The policy named by settings, re-read when the file changes (no restart needed between demo runs)."""
    path = get_settings().severity_policy_path
    key = str(path)
    mtime = path.stat().st_mtime if path.exists() else -1.0
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        policy = load_policy(path)
        _cache[key] = (mtime, policy)
        return policy


def clear_policy_cache() -> None:
    with _cache_lock:
        _cache.clear()
