"""allow awaiting_review campaign status

Revision ID: 002
Revises: 001
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
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
                'published',
                'failed',
                'cancelled',
                'archived'
            )
        )
        """
    )
