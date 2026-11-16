"""Notification channels for the Incident Bridge: Teams Adaptive Cards, SMTP email and the on-disk outbox."""
from opsagent.notify.cards import (
    build_delay_card,
    build_stage1_card,
    build_stage2_card,
    card_to_html,
    card_to_markdown,
    wrap_for_teams,
)
from opsagent.notify.deliver import build_card, deliver, deliver_delay_notice
from opsagent.notify.email import build_eml, render_email, send_email
from opsagent.notify.outbox import write_outbox
from opsagent.notify.teams import send_card

__all__ = [
    "build_card",
    "build_delay_card",
    "build_eml",
    "build_stage1_card",
    "build_stage2_card",
    "card_to_html",
    "card_to_markdown",
    "deliver",
    "deliver_delay_notice",
    "render_email",
    "send_card",
    "send_email",
    "wrap_for_teams",
    "write_outbox",
]
