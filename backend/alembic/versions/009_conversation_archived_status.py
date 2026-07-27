"""allow archived conversation status

Adds a soft-delete/archive option for the conversation sidebar — user
requested a way to clean up failed conversations (2026-07-26) without
permanently deleting them. Mirrors migration 004's pattern for extending
the same CHECK constraint.

Revision ID: 009
Revises: 008
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_status_check")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_status_check
        CHECK (
            status IN (
                'collecting',
                'awaiting_confirmation',
                'processing',
                'reviewing',
                'complete',
                'archived'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("UPDATE conversations SET status = 'collecting' WHERE status = 'archived'")
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_status_check")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_status_check
        CHECK (
            status IN (
                'collecting',
                'awaiting_confirmation',
                'processing',
                'reviewing',
                'complete'
            )
        )
        """
    )
