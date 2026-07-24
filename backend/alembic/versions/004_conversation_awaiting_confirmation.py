"""allow awaiting_confirmation conversation status

Revision ID: 004
Revises: 003
Create Date: 2026-07-20
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
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
                'complete'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("UPDATE conversations SET status = 'collecting' WHERE status = 'awaiting_confirmation'")
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_status_check")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_status_check
        CHECK (status IN ('collecting', 'processing', 'reviewing', 'complete'))
        """
    )
