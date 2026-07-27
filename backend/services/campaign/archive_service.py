"""Campaign archiving — soft (status='archived'), never a delete.

User's permission split (2026-07-26): admins can archive any campaign
regardless of status; regular users can only archive campaigns that are
genuinely stuck or failed — never one that's `awaiting_review` or
`published`, since those still need a human decision or are already live.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.database import get_db
from sqlalchemy import text

# "Stuck" thresholds — sensible defaults, not derived from any hard
# requirement. Normal runs finish in minutes (confirmed via worker logs,
# 2026-07-26), so an hour in queued/running is already abnormal. A day
# with a draft never sent to review reads as abandoned, not "still
# deciding". Tune here if these prove wrong in practice.
_STUCK_RUNNING_AFTER = timedelta(hours=1)
_STUCK_DRAFT_AFTER = timedelta(hours=24)


def _regular_user_can_archive(row: dict) -> bool:
    status = row["status"]
    now = datetime.now(UTC)

    if status == "failed":
        return True
    if status in ("queued", "running"):
        started = row["started_at"] or row["created_at"]
        return bool(started) and (now - started) > _STUCK_RUNNING_AFTER
    if status == "draft":
        return bool(row["created_at"]) and (now - row["created_at"]) > _STUCK_DRAFT_AFTER
    # awaiting_review, published, cancelled, already archived — never for
    # a regular user, regardless of age.
    return False


async def archive_campaign(campaign_id: str, *, is_admin: bool) -> None:
    """Raises LookupError (404) or PermissionError (403) for the router to
    translate into HTTP status codes."""
    async with get_db() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, started_at, created_at FROM campaigns "
                    "WHERE id = CAST(:campaign_id AS UUID)"
                ),
                {"campaign_id": campaign_id},
            )
        ).mappings().first()

        if row is None:
            raise LookupError("campaign not found")
        if not is_admin and not _regular_user_can_archive(row):
            raise PermissionError(
                f"campaign status '{row['status']}' cannot be archived by a non-admin user"
            )

        await conn.execute(
            text("UPDATE campaigns SET status = 'archived' WHERE id = CAST(:campaign_id AS UUID)"),
            {"campaign_id": campaign_id},
        )
        await conn.commit()
