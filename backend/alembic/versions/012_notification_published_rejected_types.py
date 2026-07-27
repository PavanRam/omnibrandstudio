"""notifications: add campaign_published + variants_rejected types

Two more gaps in the notification matrix, both shipped in code earlier this
session without the matching migration: notify_campaign_published (item 49,
2026-07-27) and notify_variants_rejected (item 6, 2026-07-27) both insert a
`type` value this CHECK constraint never allowed — found live when campaign
019fa4b8's resume_campaign call crashed on the campaign_published insert
after a real, working publish.

Revision ID: 012
Revises: 011
Create Date: 2026-07-27
"""
from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "('draft_ready','review_task','approved','rejected','edited',"
    "'translation_failed','campaign_failed')"
)
_NEW_TYPES = (
    "('draft_ready','review_task','approved','rejected','edited',"
    "'translation_failed','campaign_failed','campaign_published','variants_rejected')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN {_NEW_TYPES})")


def downgrade() -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN {_OLD_TYPES})")
