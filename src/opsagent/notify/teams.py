"""Microsoft Teams incoming-webhook delivery of an Adaptive Card."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from opsagent.config import Settings, get_settings
from opsagent.notify.cards import wrap_for_teams
from opsagent.schemas.incident import DeliveryReceipt


def _redact(url: str) -> str:
    """Keep only scheme and host so the receipt never leaks the webhook token."""
    try:
        parsed = httpx.URL(url)
        return f"{parsed.scheme}://{parsed.host}/..."
    except Exception:  # noqa: BLE001
        return "teams-webhook"


def send_card(card: dict, settings: Settings | None = None, timeout: float = 10, stage: str = "stage1") -> DeliveryReceipt:
    """POST the wrapped card. ok when the status is < 300. Never raises."""
    s = settings or get_settings()
    url = s.teams_webhook_url.strip()
    if not url:
        return DeliveryReceipt(
            channel="teams",
            stage=stage,  # type: ignore[arg-type]
            ok=False,
            detail="not configured: set TEAMS_WEBHOOK_URL",
            sent_at=datetime.now(timezone.utc),
        )
    target = _redact(url)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=wrap_for_teams(card), headers={"Content-Type": "application/json"})
        status = resp.status_code
        body = (resp.text or "")[:200]
        if status < 300:
            return DeliveryReceipt(
                channel="teams",
                stage=stage,  # type: ignore[arg-type]
                ok=True,
                detail=f"HTTP {status}" + (f": {body}" if body and body != "1" else ""),
                target=target,
                sent_at=datetime.now(timezone.utc),
            )
        return DeliveryReceipt(
            channel="teams",
            stage=stage,  # type: ignore[arg-type]
            ok=False,
            detail=f"HTTP {status}: {body}",
            target=target,
            sent_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - delivery must never take the flow down
        return DeliveryReceipt(
            channel="teams",
            stage=stage,  # type: ignore[arg-type]
            ok=False,
            detail=f"{type(exc).__name__}: {exc}"[:500],
            target=target,
            sent_at=datetime.now(timezone.utc),
        )
