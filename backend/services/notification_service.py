"""Campaign-lifecycle notifications.

Real, persisted rows behind the notifications bell — replaces the frontend's
static ``NOTIFICATIONS`` array. Writers call :func:`notify` (or the small
lifecycle-specific wrappers below) at the existing points where a campaign
changes state; readers are the four endpoints in ``api/routers/notifications.py``.

Recipients for reviewer-facing notifications aren't a single assignee — any
user with reviewer-level access to the brand can act on a review request, so
:func:`_reviewer_ids_for_brand` fans a "new task" notification out to every
eligible user, mirroring the brand-scoping rule used elsewhere (an empty
``users.brand_ids`` means org-wide access, same as ``api/deps.py``/``reviews.py``).
"""
from __future__ import annotations

import structlog
from core.database import get_db
from core.ids import new_uuid7
from sqlalchemy import text

log = structlog.get_logger()

_REVIEWER_ROLES = ("admin", "editor", "reviewer")


async def notify(
    *,
    org_id: str,
    brand_id: str,
    recipient_user_id: str,
    type: str,
    title: str,
    body: str | None = None,
    campaign_id: str | None = None,
) -> None:
    async with get_db() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO notifications
                    (id, org_id, brand_id, recipient_user_id, type, campaign_id, title, body)
                VALUES
                    (:id, :org_id, :brand_id, :recipient_user_id, :type, :campaign_id, :title, :body)
                """
            ),
            {
                "id": new_uuid7(),
                "org_id": org_id,
                "brand_id": brand_id,
                "recipient_user_id": recipient_user_id,
                "type": type,
                "campaign_id": campaign_id,
                "title": title,
                "body": body,
            },
        )
        await conn.commit()


async def _reviewer_ids_for_brand(org_id: str, brand_id: str) -> list[str]:
    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id FROM users
                    WHERE org_id = CAST(:org_id AS UUID)
                      AND status = 'active'
                      AND roles && :roles
                      AND (brand_ids = ARRAY[]::UUID[] OR CAST(:brand_id AS UUID) = ANY(brand_ids))
                    """
                ),
                {"org_id": org_id, "roles": list(_REVIEWER_ROLES), "brand_id": brand_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def notify_draft_ready(*, org_id: str, brand_id: str, campaign_id: str, created_by: str | None, title: str) -> None:
    if not created_by:
        return
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type="draft_ready",
        title=f'"{title}" is ready for preview',
        body="Content has been generated and is waiting for you to review before sending it to reviewers.",
        campaign_id=campaign_id,
    )


async def notify_campaign_published(
    *, org_id: str, brand_id: str, campaign_id: str, created_by: str | None, title: str
) -> None:
    if not created_by:
        return
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type="campaign_published",
        title=f'"{title}" has published',
        body="Every variant was approved and the campaign has published.",
        campaign_id=campaign_id,
    )


async def notify_campaign_failed(*, org_id: str, brand_id: str, campaign_id: str, created_by: str | None, title: str) -> None:
    if not created_by:
        return
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type="campaign_failed",
        title=f'"{title}" failed to generate',
        body="No content survived the pipeline run — check the campaign for details.",
        campaign_id=campaign_id,
    )


async def notify_translation_failed(
    *, org_id: str, brand_id: str, campaign_id: str, created_by: str | None, title: str, locale: str
) -> None:
    if not created_by:
        return
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type="translation_failed",
        title=f'"{title}" — {locale} translation failed',
        body="This locale exhausted its translation retries and needs a look before the draft is sent for review.",
        campaign_id=campaign_id,
    )


async def notify_variants_rejected(
    *,
    org_id: str,
    brand_id: str,
    campaign_id: str,
    created_by: str | None,
    title: str,
    rejected_items: list[dict],
) -> None:
    """Fires once per review round when the batch finishes deciding with at
    least one rejection — not per-variant like notify_decision (which still
    fires immediately at decision time as a quick ping). This is the
    "go look at your conversation" summary paired with the assistant message
    session_manager.add_message injects into the originating conversation."""
    if not created_by or not rejected_items:
        return
    count = len(rejected_items)
    plural = "variant" if count == 1 else "variants"
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type="variants_rejected",
        title=f'"{title}" — {count} {plural} need changes',
        body="A reviewer left comments. Reply in the conversation to regenerate them.",
        campaign_id=campaign_id,
    )


async def notify_review_task(*, org_id: str, brand_id: str, campaign_id: str, title: str) -> None:
    reviewer_ids = await _reviewer_ids_for_brand(org_id, brand_id)
    for reviewer_id in reviewer_ids:
        await notify(
            org_id=org_id,
            brand_id=brand_id,
            recipient_user_id=reviewer_id,
            type="review_task",
            title=f'New review task: "{title}"',
            body="A campaign is waiting for your review decision.",
            campaign_id=campaign_id,
        )


_DECISION_TITLES = {
    "approved": "was approved",
    "rejected": "was rejected",
    "edited": "was edited by a reviewer",
}


async def notify_decision(
    *, org_id: str, brand_id: str, campaign_id: str, created_by: str | None, title: str, decision: str
) -> None:
    if not created_by or decision not in _DECISION_TITLES:
        return
    await notify(
        org_id=org_id,
        brand_id=brand_id,
        recipient_user_id=created_by,
        type=decision,
        title=f'"{title}" {_DECISION_TITLES[decision]}',
        campaign_id=campaign_id,
    )


async def unread_count(user_id: str) -> int:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM notifications WHERE recipient_user_id = CAST(:uid AS UUID) AND read_at IS NULL"
            ),
            {"uid": user_id},
        )
        return int(result.scalar_one())


async def list_notifications(user_id: str, *, limit: int = 20, offset: int = 0) -> list[dict]:
    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, type, campaign_id, title, body, read_at, created_at
                    FROM notifications
                    WHERE recipient_user_id = CAST(:uid AS UUID)
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"uid": user_id, "limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "type": r["type"],
            "campaign_id": str(r["campaign_id"]) if r["campaign_id"] else None,
            "title": r["title"],
            "body": r["body"],
            "read": r["read_at"] is not None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def mark_read(user_id: str, notification_id: str) -> bool:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE notifications SET read_at = NOW()
                WHERE id = CAST(:id AS UUID) AND recipient_user_id = CAST(:uid AS UUID) AND read_at IS NULL
                """
            ),
            {"id": notification_id, "uid": user_id},
        )
        await conn.commit()
        return result.rowcount > 0


async def mark_all_read(user_id: str) -> int:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE notifications SET read_at = NOW()
                WHERE recipient_user_id = CAST(:uid AS UUID) AND read_at IS NULL
                """
            ),
            {"uid": user_id},
        )
        await conn.commit()
        return result.rowcount
