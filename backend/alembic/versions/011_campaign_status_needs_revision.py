"""allow needs_revision campaign status

Revision ID: 011
Revises: 010
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_status_check")
    op.execute(
        """
        ALTER TABLE campaigns
        ADD CONSTRAINT campaigns_status_check
        CHECK (
            status IN (
                'draft',
                'queued',
                'running',
                'awaiting_review',
                'needs_revision',
                'published',
                'failed',
                'cancelled',
                'archived'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_status_check")
    op.execute(
        """
        ALTER TABLE campaigns
        ADD CONSTRAINT campaigns_status_check
        CHECK (
            status IN (
                'draft',
                'queued',
                'running',
                'awaiting_review',
                'published',
                'failed',
                'cancelled',
                'archived'
            )
        )
        """
    )
