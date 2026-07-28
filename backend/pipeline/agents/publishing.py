"""Publishing agent — demo SMTP delivery via MailHog.

All channels are delivered as HTML email regardless of their target channel.
Each email is channel-styled (LinkedIn card, SMS bubble, etc.) so testers
can verify content visually in the MailHog UI at http://localhost:8025.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from sqlalchemy import text

from core.config import settings
from core.database import get_db
from pipeline.agents.base import publish_campaign_event, safe_agent_run
from pipeline.agents.email_templates import build_campaign_email_html
from pipeline.state import OmniBrandState

log = structlog.get_logger()

_ELIGIBLE_STATUSES = {"approved", "generated", "personalized"}


async def _resolve_creator_email(user_id: str) -> str | None:
    """The campaign creator's real email, if `state["user_id"]` resolves to
    an actual user row. Not every campaign has one — server-to-server/API-key
    callers use a non-UUID actor sentinel (see CLAUDE.md's dual-auth note),
    so this fails open (returns None) rather than raising, letting the
    caller fall back to the configured demo recipient list."""
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None
    try:
        async with get_db() as conn:
            result = await conn.execute(
                text("SELECT email FROM users WHERE id = CAST(:uid AS UUID)"),
                {"uid": user_id},
            )
            row = result.mappings().first()
            return str(row["email"]) if row and row["email"] else None
    except Exception as exc:  # noqa: BLE001
        log.warning("publish_creator_email_lookup_failed", user_id=user_id, error=str(exc))
        return None


async def publishing_agent(state: OmniBrandState) -> dict:
    """Last pipeline node.  Sends one HTML email per eligible variant."""

    async def _impl(state: OmniBrandState) -> dict:
        # Lazy import to avoid ModuleNotFoundError at API startup
        import aiosmtplib

        campaign_id = state.get("campaign_id", "")
        brief = state.get("brief")

        # ── 1. Resolve recipient list ──────────────────────────────────────
        # The campaign creator's own email is the real, meaningful recipient
        # (2026-07-27) — previously every campaign, from every user, always
        # went to one shared static demo address regardless of who made it.
        # Falls back to the configured demo list when there's no resolvable
        # creator (API-key-created campaigns, or the env var override for
        # local testing without a seeded user).
        creator_email = await _resolve_creator_email(state.get("user_id", ""))
        recipients = (
            [creator_email]
            if creator_email
            else [
                r.strip()
                for r in (settings.PUBLISH_RECIPIENT_EMAILS or "").split(",")
                if r.strip()
            ]
        )
        if not recipients:
            log.warning(
                "publish_skipped_no_recipients",
                campaign_id=campaign_id,
            )
            return {
                "publication_receipts": [],
                "variants": [],
                "current_phase": "published",
            }

        # ── 2. Filter eligible variants ────────────────────────────────────
        eligible = [
            v
            for v in state.get("variants", [])
            if v.get("status") in _ELIGIBLE_STATUSES
        ]
        if not eligible:
            log.warning(
                "publish_no_eligible_variants",
                campaign_id=campaign_id,
                total_variants=len(state.get("variants", [])),
            )
            return {
                "publication_receipts": [],
                "variants": [],
                "current_phase": "published",
            }

        # Index aggregated scores by variant_id for O(1) lookup
        score_index = {
            s["variant_id"]: s
            for s in state.get("aggregated_scores", [])
            if s.get("variant_id")
        }

        receipts: list[dict] = []
        updated_variants: list[dict] = []
        errors: list[str] = []

        objective = (brief.get("objective") or "Campaign") if brief else "Campaign"

        for variant in eligible:
            task_id = variant.get("task_id", "")
            channel = (variant.get("channel") or "email").lower()
            locale = variant.get("locale", "en")

            # ── 3a. Resolve content ────────────────────────────────────────
            content = (
                variant.get("final_content")
                or variant.get("personalized_content")
                or variant.get("generated_content")
                or ""
            )

            # ── 3b. Look up score ──────────────────────────────────────────
            score = score_index.get(task_id)

            # ── 3c. Build HTML ─────────────────────────────────────────────
            html_body = build_campaign_email_html(variant, brief, score)

            # ── 3d. Build plain-text fallback ─────────────────────────────
            plain_body = (
                f"OmniBrand Studio — Demo Email\n"
                f"{'=' * 44}\n"
                f"Channel : {channel.upper()}\n"
                f"Locale  : {locale}\n"
                f"Segment : {variant.get('segment', '')}\n"
                f"{'=' * 44}\n\n"
                f"{content}\n\n"
                f"---\n"
                f"Generated by OmniBrand Studio (demo mode)\n"
            )

            # ── 3e. Build MIME message ─────────────────────────────────────
            message_id = f"<{uuid.uuid4()}@omnibrand-demo>"
            subject = (
                f"[OmniBrand Demo] {channel.upper()} | "
                f"{objective[:60]} — {locale}"
            )

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = "OmniBrand Studio <omnibrand-demo@localhost>"
            msg["To"] = ", ".join(recipients)
            msg["Message-ID"] = message_id
            msg["X-OmniBrand-Campaign"] = campaign_id
            msg["X-OmniBrand-Channel"] = channel
            msg["X-OmniBrand-Task"] = task_id

            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            # ── 3e. Send ───────────────────────────────────────────────────
            published_at = datetime.now(UTC).isoformat()
            publish_status = "sent"
            error_message: str | None = None

            try:
                await aiosmtplib.send(
                    msg,
                    hostname=settings.PUBLISH_SMTP_HOST,
                    port=settings.PUBLISH_SMTP_PORT,
                    timeout=10,
                )
                log.info(
                    "variant_published",
                    campaign_id=campaign_id,
                    task_id=task_id,
                    channel=channel,
                    recipients=len(recipients),
                    message_id=message_id,
                )
            except Exception as exc:
                publish_status = "failed"
                error_message = str(exc)
                errors.append(f"publishing_agent: send failed for {task_id}: {exc}")
                log.error(
                    "variant_publish_failed",
                    campaign_id=campaign_id,
                    task_id=task_id,
                    channel=channel,
                    error=str(exc),
                )

            # ── 3f. Build receipt ──────────────────────────────────────────
            receipts.append(
                {
                    "variant_id": task_id,
                    "channel": channel,
                    "locale": locale,
                    "platform_publication_id": message_id,
                    "public_url": None,
                    "adapter_used": "smtp_demo",
                    "publish_status": publish_status,
                    "published_at": published_at,
                    "error_message": error_message,
                }
            )

            # ── 3g. Update variant status ──────────────────────────────────
            updated = dict(variant)
            updated["status"] = "published" if publish_status == "sent" else "publish_failed"
            if updated.get("final_content") is None and content:
                updated["final_content"] = content
            updated_variants.append(updated)

        # ── 4. Return partial state ────────────────────────────────────────
        result: dict = {
            "publication_receipts": receipts,
            "variants": updated_variants,
            "current_phase": "published",
        }
        if errors:
            result["errors"] = errors
        await publish_campaign_event(
            campaign_id=campaign_id,
            agent="publishing_agent",
            phase="publishing_complete",
            payload={"published": len(receipts), "error_count": len(errors)},
        )
        return result

    return await safe_agent_run(_impl, state)
