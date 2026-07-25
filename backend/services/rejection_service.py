"""Rejection-notice email — sent to the campaign requester when a review is rejected.

Layered on top of develop's Airtable human-review flow: when a reviewer sets
``Decision = Rejected`` (in Airtable, the app UI, or Postman), the poller/route
calls :func:`services.review_service.apply_decision`, which — for a rejection —
calls :func:`send_rejection_email` here.

Reuses the publishing agent's SMTP settings (``PUBLISH_SMTP_HOST``/``PORT`` →
MailHog). Best-effort: a send failure logs a warning and returns ``False``; it
never raises, so a mail hiccup never blocks the decision from being applied.
"""

from __future__ import annotations

import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import structlog

from core.config import settings
from pipeline.agents.email_templates import build_rejection_email_html

log = structlog.get_logger()

_SMTP_TIMEOUT = 10


async def send_rejection_email(
    to_email: str | None,
    reason: str,
    *,
    campaign_id: str = "",
    objective: str = "",
) -> bool:
    """Send one "campaign rejected" email. Returns True on success.

    No-op (returns False) when no recipient is resolved. Never raises.
    """
    if not to_email:
        log.warning("rejection_email_skipped_no_recipient", campaign_id=campaign_id)
        return False

    html_body = build_rejection_email_html(
        reason=reason,
        objective=objective,
        campaign_id=campaign_id,
        recipient=to_email,
    )
    plain_body = (
        "OmniBrand Studio — Campaign Rejected\n"
        f"{'=' * 44}\n"
        f"Campaign : {campaign_id or '-'}\n"
        f"Objective: {objective or '-'}\n"
        f"{'=' * 44}\n\n"
        "Your campaign was rejected during human review. "
        "No content has been published.\n\n"
        f"Reason for rejection:\n{reason or 'No reason provided.'}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[OmniBrand] Your campaign was rejected"
    msg["From"] = "OmniBrand Studio <omnibrand-demo@localhost>"
    msg["To"] = to_email
    msg["Message-ID"] = f"<{uuid.uuid4()}@omnibrand-demo>"
    if campaign_id:
        msg["X-OmniBrand-Campaign"] = campaign_id
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.PUBLISH_SMTP_HOST,
            port=settings.PUBLISH_SMTP_PORT,
            timeout=_SMTP_TIMEOUT,
        )
        log.info("rejection_email_sent", campaign_id=campaign_id, recipient=to_email)
        return True
    except Exception as exc:  # best-effort — never blocks the decision
        log.error(
            "rejection_email_failed",
            campaign_id=campaign_id,
            recipient=to_email,
            error=str(exc),
        )
        return False
