"""persist captured/changes chips on conversation_messages

conversation_messages only ever stored plain text content — the "CAPTURED"
and "UPDATED" chips shown under an assistant turn (brief_updates /
brief_changes) were computed live per-turn and sent only over the
WebSocket, never persisted. Reloading a conversation (page reload, or
switching away and back) silently lost them, falling back to bare text.

Revision ID: 013
Revises: 012
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS captured JSONB")
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS changes JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS changes")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS captured")
