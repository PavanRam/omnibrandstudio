"""add chat-first core tables

Revision ID: 003
Revises: 002
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID NOT NULL REFERENCES brands(id),
            org_id UUID NOT NULL REFERENCES orgs(id),
            created_by UUID REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'collecting'
                CHECK (status IN ('collecting', 'processing', 'reviewing', 'complete')),
            partial_brief JSONB NOT NULL DEFAULT '{}'::JSONB,
            active_campaign_id UUID REFERENCES campaigns(id),
            campaign_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
            summary TEXT,
            summary_updated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_conversations_created_by_brand_created
        ON conversations(created_by, brand_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE conversation_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            intent_classified TEXT,
            campaign_id UUID REFERENCES campaigns(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_conversation_messages_conversation_created
        ON conversation_messages(conversation_id, created_at)
        """
    )

    op.execute(
        """
        CREATE TABLE campaign_revisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id),
            variant_id UUID REFERENCES content_variants(id),
            revision_number INT NOT NULL DEFAULT 1,
            trigger TEXT NOT NULL
                CHECK (trigger IN ('initial', 'edit_content', 'add_channel', 'regenerate')),
            resumed_from_node TEXT,
            user_edit TEXT,
            cost_usd NUMERIC(10,6),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_campaign_revisions_campaign_created
        ON campaign_revisions(campaign_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE brand_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID NOT NULL REFERENCES brands(id),
            org_id UUID NOT NULL REFERENCES orgs(id),
            preferred_channels JSONB NOT NULL DEFAULT '[]'::JSONB,
            tone_by_channel JSONB NOT NULL DEFAULT '{}'::JSONB,
            top_ctas JSONB NOT NULL DEFAULT '[]'::JSONB,
            recent_campaign_summary TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_brand_memories_brand_id UNIQUE (brand_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_brand_memories_org ON brand_memories(org_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_brand_memories_org")
    op.execute("DROP TABLE IF EXISTS brand_memories")

    op.execute("DROP INDEX IF EXISTS idx_campaign_revisions_campaign_created")
    op.execute("DROP TABLE IF EXISTS campaign_revisions")

    op.execute("DROP INDEX IF EXISTS idx_conversation_messages_conversation_created")
    op.execute("DROP TABLE IF EXISTS conversation_messages")

    op.execute("DROP INDEX IF EXISTS idx_conversations_created_by_brand_created")
    op.execute("DROP TABLE IF EXISTS conversations")
