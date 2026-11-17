"""Rule-based classification and severity. Deterministic; the LLM only comments on the result.

Thresholds and the severity rules come from the severity policy (config/severity.yaml, see
opsagent.parsing.severity_policy); the rule logic itself stays here, in code, with tests.
"""
from __future__ import annotations

from opsagent.parsing.severity_policy import SeverityPolicy, get_policy
from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Classification, Evidence, Severity

_KNOWN_REASONS = {"memory", "cpu", "disk", "network"}


def classify(event: RawEvent, evidence: Evidence, policy: SeverityPolicy | None = None) -> Classification:
    """Apply the triage rules in order and return the first match.

    1. A kernel OOM kill in the system log                         -> memory / process_oom_kill / high
    2. Leak slope >= policy slope and < policy mem avail (50 / 10)  -> memory / rapid_growth / medium
    3. Alarm event_type is cpu                                      -> cpu / sustained_high_cpu / medium
    4. Otherwise the alarm's event_type                             -> <event_type> / threshold_breach / low
    """
    thresholds = (policy or get_policy()).classification
    if evidence.oom_events:
        o = evidence.oom_events[-1]
        rss = f"{o.anon_rss_kb // 1024} MB anon RSS" if o.anon_rss_kb else "unknown RSS"
        where = f" in {o.cgroup}" if o.cgroup else ""
        return Classification(
            reason="memory",
            sub_reason="process_oom_kill",
            confidence="high",
            rule="oom_kill_in_system_log",
            rationale=f"Kernel killed {o.killed_process} (pid {o.killed_pid}){where} at {rss}.",
        )

    lp = evidence.leak_profile
    if (
        lp is not None
        and lp.slope_mb_per_min >= thresholds.rapid_growth_min_slope_mb_per_min
        and lp.mem_available_pct_at_kill is not None
        and lp.mem_available_pct_at_kill < thresholds.rapid_growth_max_mem_available_pct
    ):
        return Classification(
            reason="memory",
            sub_reason="rapid_growth",
            confidence="medium",
            rule="leak_profile_rapid_growth",
            rationale=(
                f"RSS grew {lp.slope_mb_per_min:.0f} MB/min from {lp.first_rss_mb:.0f} to {lp.peak_rss_mb:.0f} MB "
                f"with {lp.mem_available_pct_at_kill:.1f}% memory available at the end."
            ),
        )

    event_type = (event.event_type or "unknown").lower()
    if event_type == "cpu":
        return Classification(
            reason="cpu",
            sub_reason="sustained_high_cpu",
            confidence="medium",
            rule="alarm_event_type",
            rationale=f"Alarm {event.alarm.name} is a CPU alarm and no memory evidence was found in the logs.",
        )

    reason = event_type if event_type in _KNOWN_REASONS else "unknown"
    return Classification(
        reason=reason,  # type: ignore[arg-type]
        sub_reason="threshold_breach",
        confidence="low",
        rule="alarm_event_type_fallback",
        rationale=f"Only the alarm {event.alarm.name} ({event_type}) supports this; the logs show no matching evidence.",
    )


def severity(event: RawEvent, evidence: Evidence, classification: Classification, policy: SeverityPolicy | None = None) -> Severity:
    """Severity from the evidence, by the policy's ordered rules (first match wins, else the policy default).

    The shipped policy: critical when an OOM kill happened, the restart counter reached 2, or memory available
    fell under 5 %; warning when the classification confidence is high or medium; info otherwise.
    """
    return (policy or get_policy()).severity_for(event, evidence, classification)
