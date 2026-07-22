"""golden dataset tenant isolation + versioned sets

Revision ID: 005
Revises: 004
Create Date: 2026-07-22

Adds the versioned golden/silver dataset model:
  • golden_dataset_set — a draft→active→archived collection pinned to a brand
    guide version (one active set per org+brand+locale).
  • golden_dataset — gains org_id (tenant isolation), status (silver→golden),
    source provenance, created_by, and set_id membership.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── golden_dataset_set ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE golden_dataset_set (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            locale TEXT NOT NULL DEFAULT 'en-US',
            guide_version TEXT,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','active','archived')),
            source TEXT NOT NULL DEFAULT 'llm_generated'
                CHECK (source IN ('llm_generated','human_curated')),
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            activated_at TIMESTAMPTZ
        )
    """)
    # Exactly one active set per (org, brand, locale) — mirrors idx_prompt_active.
    op.execute(
        "CREATE UNIQUE INDEX idx_golden_set_active "
        "ON golden_dataset_set(org_id, brand_id, locale) WHERE status = 'active'"
    )
    op.execute("CREATE INDEX idx_golden_set_org_brand ON golden_dataset_set(org_id, brand_id)")

    # ── golden_dataset: tenant isolation + provenance + set membership ─────
    op.execute(
        "ALTER TABLE golden_dataset "
        "ADD COLUMN org_id UUID REFERENCES orgs(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE golden_dataset ADD COLUMN status TEXT NOT NULL DEFAULT 'silver' "
        "CHECK (status IN ('silver','golden'))"
    )
    op.execute(
        "ALTER TABLE golden_dataset ADD COLUMN source TEXT NOT NULL DEFAULT 'llm_generated' "
        "CHECK (source IN ('llm_generated','human_curated'))"
    )
    op.execute("ALTER TABLE golden_dataset ADD COLUMN created_by UUID REFERENCES users(id)")
    op.execute(
        "ALTER TABLE golden_dataset ADD COLUMN set_id UUID "
        "REFERENCES golden_dataset_set(id) ON DELETE CASCADE"
    )

    # Backfill org_id from the owning brand, then enforce tenant NOT NULLs.
    op.execute(
        "UPDATE golden_dataset gd SET org_id = b.org_id "
        "FROM brands b WHERE gd.brand_id = b.id AND gd.org_id IS NULL"
    )
    # Drop any orphaned rows that cannot be tenant-scoped (no brand) so the
    # NOT NULL constraints can be applied cleanly.
    op.execute("DELETE FROM golden_dataset WHERE org_id IS NULL OR brand_id IS NULL")
    op.execute("ALTER TABLE golden_dataset ALTER COLUMN org_id SET NOT NULL")
    op.execute("ALTER TABLE golden_dataset ALTER COLUMN brand_id SET NOT NULL")

    op.execute("CREATE INDEX idx_golden_org_brand ON golden_dataset(org_id, brand_id, status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_golden_org_brand")
    op.execute("ALTER TABLE golden_dataset ALTER COLUMN brand_id DROP NOT NULL")
    op.execute("ALTER TABLE golden_dataset DROP COLUMN IF EXISTS set_id")
    op.execute("ALTER TABLE golden_dataset DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE golden_dataset DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE golden_dataset DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE golden_dataset DROP COLUMN IF EXISTS org_id")

    op.execute("DROP INDEX IF EXISTS idx_golden_set_org_brand")
    op.execute("DROP INDEX IF EXISTS idx_golden_set_active")
    op.execute("DROP TABLE IF EXISTS golden_dataset_set")
