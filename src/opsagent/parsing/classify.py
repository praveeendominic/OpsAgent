"""Rule-based classification and severity. Deterministic; the LLM only comments on the result."""
from __future__ import annotations

from opsagent.schemas.raw import RawEvent
from opsagent.schemas.triage import Classification, Evidence, Severity

_KNOWN_REASONS = {"memory", "cpu", "disk", "network"}

RAPID_GROWTH_MIN_SLOPE_MB_PER_MIN = 50.0
RAPID_GROWTH_MAX_MEM_AVAILABLE_PCT = 10.0
CRITICAL_RESTART_COUNT = 2
CRITICAL_MEM_AVAILABLE_PCT = 5.0


def classify(event: RawEvent, evidence: Evidence) -> Classification:
    """Apply the triage rules in order and return the first match.

    1. A kernel OOM kill in the system log            -> memory / process_oom_kill / high
    2. Leak slope >= 50 MB/min and < 10 % mem avail    -> memory / rapid_growth / medium
    3. Alarm event_type is cpu                         -> cpu / sustained_high_cpu / medium
    4. Otherwise the alarm's event_type                -> <event_type> / threshold_breach / low
    """
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
        and lp.slope_mb_per_min >= RAPID_GROWTH_MIN_SLOPE_MB_PER_MIN
        and lp.mem_available_pct_at_kill is not None
        and lp.mem_available_pct_at_kill < RAPID_GROWTH_MAX_MEM_AVAILABLE_PCT
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


def severity(event: RawEvent, evidence: Evidence, classification: Classification) -> Severity:
    """Severity from the evidence.

    critical: an OOM kill happened, the restart counter reached 2, or memory available fell under 5 %.
    warning:  classification confidence is high or medium without any of the above.
    info:     everything else.
    """
    lp = evidence.leak_profile
    if evidence.oom_events:
        return "critical"
    if evidence.restart_count is not None and evidence.restart_count >= CRITICAL_RESTART_COUNT:
        return "critical"
    if lp is not None and lp.mem_available_pct_at_kill is not None and lp.mem_available_pct_at_kill < CRITICAL_MEM_AVAILABLE_PCT:
        return "critical"
    if classification.confidence in ("high", "medium"):
        return "warning"
    return "info"
