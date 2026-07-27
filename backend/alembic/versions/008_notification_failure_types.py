"""notifications: add translation_failed + campaign_failed types

Closes two gaps in the notification matrix (2026-07-26): the creator never
learned when a campaign hard-failed (no variant survived), and translation
failures had an escalation path that was a logged no-op. See next_tasks.md
item 1.

Revision ID: 008
Revises: 007
Create Date: 2026-07-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = "('draft_ready','review_task','approved','rejected','edited')"
_NEW_TYPES = "('draft_ready','review_task','approved','rejected','edited','translation_failed','campaign_failed')"


def upgrade() -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN {_NEW_TYPES})")


def downgrade() -> None:
    op.execute("ALTER TABLE notifications DROP CONSTRAINT notifications_type_check")
    op.execute(f"ALTER TABLE notifications ADD CONSTRAINT notifications_type_check CHECK (type IN {_OLD_TYPES})")
