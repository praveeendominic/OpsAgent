"""Notification channels for the Incident Bridge: Teams Adaptive Cards, SMTP email, ServiceNow incidents, xMatters
paging and the on-disk outbox."""
from opsagent.notify.cards import (
    build_delay_card,
    build_stage1_card,
    build_stage2_card,
    card_to_html,
    card_to_markdown,
    wrap_for_teams,
)
from opsagent.notify.deliver import build_card, deliver, deliver_closure, deliver_delay_notice
from opsagent.notify.servicenow import send_stage as send_servicenow_stage
from opsagent.notify.servicenow import send_work_note as send_servicenow_work_note
from opsagent.notify.email import build_eml, render_email, send_email
from opsagent.notify.outbox import write_outbox
from opsagent.notify.teams import send_card
from opsagent.notify.xmatters import send_note as send_xmatters_note
from opsagent.notify.xmatters import send_stage as send_xmatters_stage

__all__ = [
    "build_card",
    "build_delay_card",
    "build_eml",
    "build_stage1_card",
    "build_stage2_card",
    "card_to_html",
    "card_to_markdown",
    "deliver",
    "deliver_closure",
    "deliver_delay_notice",
    "render_email",
    "send_card",
    "send_email",
    "send_servicenow_stage",
    "send_servicenow_work_note",
    "send_xmatters_note",
    "send_xmatters_stage",
    "wrap_for_teams",
    "write_outbox",
]
