"""The severity policy: loading and validation, rule evaluation, ServiceNow mapping, paging, and the shipped file."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsagent.config import PROJECT_ROOT
from opsagent.parsing import severity_policy as sp
from opsagent.parsing.classify import classify, severity
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Classification, Evidence, LeakProfile, OOMEvent
from tests.test_parsing import event  # noqa: F401 - fixture

SHIPPED = PROJECT_ROOT / "config" / "severity.yaml"


def _classification(confidence: str = "low") -> Classification:
    return Classification(reason="memory", sub_reason="threshold_breach", confidence=confidence, rule="t", rationale="t")  # type: ignore[arg-type]


_T0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _oom() -> OOMEvent:
    return OOMEvent(timestamp=_T0, killed_process="python3", killed_pid=1234, anon_rss_kb=900_000)


def _leak(slope: float, mem_pct: float | None) -> LeakProfile:
    return LeakProfile(start=_T0, end=_T0, first_rss_mb=50, peak_rss_mb=900, slope_mb_per_min=slope, mem_available_pct_at_kill=mem_pct)


# --------------------------------------------------------------------------------------------------- shipped file
def test_shipped_policy_equals_the_built_in_defaults() -> None:
    shipped = sp.load_policy(SHIPPED)
    assert shipped.source == str(SHIPPED) and len(shipped.digest) == 12
    assert shipped.model_dump() == sp.default_policy().model_dump()


def test_missing_file_means_defaults_and_bad_file_raises(tmp_path: Path) -> None:
    p = sp.load_policy(tmp_path / "nope.yaml")
    assert p.source == sp.BUILT_IN_SOURCE and p.pages("critical") and not p.pages("warning")

    bad = tmp_path / "bad.yaml"
    bad.write_text("rules:\n  - severity: crtical\n    when: oom_event\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="severity"):
        sp.load_policy(bad)

    bad.write_text("rules:\n  - severity: critical\n    when: memory_is_low\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="when"):
        sp.load_policy(bad)

    bad.write_text("rules:\n  - severity: critical\n    when: restart_count_at_least\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="numeric value"):
        sp.load_policy(bad)

    bad.write_text("rules:\n  - severity: critical\n    when: oom_event\n    value: 3\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="takes no value"):
        sp.load_policy(bad)

    bad.write_text("rules: []\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError):
        sp.load_policy(bad)

    bad.write_text("rules:\n  - severity: info\n    when: oom_event\nsurprise: 1\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="surprise"):
        sp.load_policy(bad)

    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(sp.SeverityPolicyError, match="mapping"):
        sp.load_policy(bad)


# --------------------------------------------------------------------------------------------------- rule kinds
def test_each_rule_kind(event: RawEvent) -> None:  # noqa: F811
    def rule(kind: str, value=None, sev: str = "critical") -> sp.SeverityRule:
        return sp.SeverityRule(severity=sev, when=kind, value=value)  # type: ignore[arg-type]

    low = _classification("low")
    assert rule("oom_event").matches(event, Evidence(oom_events=[_oom()]), low)
    assert not rule("oom_event").matches(event, Evidence(), low)

    assert rule("restart_count_at_least", 2).matches(event, Evidence(restart_count=2), low)
    assert not rule("restart_count_at_least", 2).matches(event, Evidence(restart_count=1), low)
    assert not rule("restart_count_at_least", 2).matches(event, Evidence(), low)

    assert rule("mem_available_pct_below", 5).matches(event, Evidence(leak_profile=_leak(1, 4.9)), low)
    assert not rule("mem_available_pct_below", 5).matches(event, Evidence(leak_profile=_leak(1, 5.0)), low)
    assert not rule("mem_available_pct_below", 5).matches(event, Evidence(leak_profile=_leak(1, None)), low)

    assert rule("leak_slope_at_least", 50).matches(event, Evidence(leak_profile=_leak(50, 40)), low)
    assert not rule("leak_slope_at_least", 50).matches(event, Evidence(leak_profile=_leak(49.9, 40)), low)

    conf = rule("classification_confidence_in", ["High", " medium"])
    assert conf.value == ["high", "medium"]
    assert conf.matches(event, Evidence(), _classification("medium"))
    assert not conf.matches(event, Evidence(), low)

    cpu = event.model_copy(update={"event_type": "cpu"})
    assert rule("alarm_event_type_in", ["cpu"]).matches(cpu, Evidence(), low)
    assert not rule("alarm_event_type_in", ["cpu"]).matches(event, Evidence(), low)


def test_first_match_wins_and_default_applies(event: RawEvent) -> None:  # noqa: F811
    policy = sp.SeverityPolicy(
        rules=[
            sp.SeverityRule(severity="warning", when="alarm_event_type_in", value=["cpu"]),  # type: ignore[arg-type]
            sp.SeverityRule(severity="critical", when="oom_event"),  # type: ignore[arg-type]
        ],
        default="warning",
    )
    cpu = event.model_copy(update={"event_type": "cpu"})
    # the cpu rule comes first, so even with an OOM in the evidence a cpu alarm is a warning under this policy
    assert policy.severity_for(cpu, Evidence(oom_events=[_oom()]), _classification()) == "warning"
    assert policy.severity_for(event, Evidence(oom_events=[_oom()]), _classification()) == "critical"
    assert policy.severity_for(event, Evidence(), _classification()) == "warning"
    assert policy.matched_rule(event, Evidence(), _classification()) == "default -> warning"
    assert policy.matched_rule(event, Evidence(oom_events=[_oom()]), _classification()) == "oom_event -> critical"


# --------------------------------------------------------------------------------------------------- classify / severity
def test_classification_thresholds_come_from_the_policy(event: RawEvent) -> None:  # noqa: F811
    evidence = Evidence(leak_profile=_leak(30, 8))
    assert classify(event, evidence).sub_reason == "threshold_breach"  # shipped: needs >= 50 MB/min
    relaxed = sp.default_policy().model_copy(update={"classification": sp.ClassificationThresholds(rapid_growth_min_slope_mb_per_min=20)})
    assert classify(event, evidence, policy=relaxed).sub_reason == "rapid_growth"


def test_severity_follows_an_explicit_policy(event: RawEvent) -> None:  # noqa: F811
    evidence = Evidence(restart_count=1)
    c = _classification("low")
    assert severity(event, evidence, c) == "info"
    strict = sp.SeverityPolicy(rules=[sp.SeverityRule(severity="critical", when="restart_count_at_least", value=1)])  # type: ignore[arg-type]
    assert severity(event, evidence, c, policy=strict) == "critical"


# --------------------------------------------------------------------------------------------------- servicenow / paging
def test_ticket_priority_map_and_paging() -> None:
    p = sp.default_policy()
    assert p.ticket_priority("critical") == ("1", "1")
    assert p.ticket_priority("warning") == ("2", "2")
    assert p.ticket_priority("info") == ("3", "3")
    assert p.ticket_priority("bogus") == ("3", "3")

    custom = sp.SeverityPolicy.model_validate({
        "rules": [{"severity": "critical", "when": "oom_event"}],
        "servicenow": {"warning": {"impact": 1, "urgency": 2}},  # the other two fall back to defaults
        "paging": {"immediate": ["critical", "warning"]},
    })
    assert custom.ticket_priority("warning") == ("1", "2")
    assert custom.ticket_priority("critical") == ("1", "1")
    assert custom.pages("warning") and not custom.pages("info")

    with pytest.raises(Exception):
        sp.SeverityPolicy.model_validate({"rules": [{"severity": "critical", "when": "oom_event"}],
                                          "servicenow": {"critical": {"impact": 0, "urgency": 1}}})


def test_describe_is_json_friendly_and_names_the_rules() -> None:
    d = sp.load_policy(SHIPPED).describe()
    assert d["rules"][0] == "oom_event -> critical"
    assert d["rules"][1] == "restart_count_at_least 2.0 -> critical"
    assert d["servicenow"]["critical"] == "impact 1 / urgency 1"
    assert d["paging_immediate"] == ["critical"]
    assert d["source"].endswith("severity.yaml") and d["digest"]


# --------------------------------------------------------------------------------------------------- settings + cache
def test_get_policy_follows_the_setting_and_rereads_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opsagent import config

    path = tmp_path / "severity.yaml"
    path.write_text("rules:\n  - severity: warning\n    when: oom_event\npaging:\n  immediate: [critical, warning]\n", encoding="utf-8")
    monkeypatch.setenv("OPSAGENT_SEVERITY_POLICY", str(path))
    config.get_settings.cache_clear()
    sp.clear_policy_cache()
    try:
        p1 = sp.get_policy()
        assert p1.source == str(path) and p1.pages("warning")
        assert sp.get_policy() is p1  # cached while the file is unchanged

        path.write_text("rules:\n  - severity: info\n    when: oom_event\n", encoding="utf-8")
        import os
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
        p2 = sp.get_policy()
        assert p2 is not p1 and p2.rules[0].severity == "info" and not p2.pages("warning")
    finally:
        config.get_settings.cache_clear()
        sp.clear_policy_cache()
