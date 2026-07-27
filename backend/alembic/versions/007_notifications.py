"""notifications table

Real, persisted campaign-lifecycle notifications, replacing the frontend's
static NOTIFICATIONS array. See next_tasks.md "Real notifications system".

Revision ID: 007
Revises: 006
Create Date: 2026-07-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            recipient_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL
                CHECK (type IN ('draft_ready','review_task','approved','rejected','edited')),
            campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT,
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Unread-count polling and the panel list both filter by recipient first.
    op.execute(
        "CREATE INDEX idx_notifications_recipient_unread "
        "ON notifications(recipient_user_id, created_at DESC) WHERE read_at IS NULL"
    )
    op.execute(
        "CREATE INDEX idx_notifications_recipient ON notifications(recipient_user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications")
