"""allowed_locales on brands, customer_segments table, brand_guides quarantine status

Revision ID: 006
Revises: 005
Create Date: 2026-07-25

Covers Phase 2.5 (RAG quarantine) and Phase 2.7 (segments→Postgres, allowed_locales):
  • brands.allowed_locales TEXT[] — drives locale chip-select in admin + chat validation
  • brand_guides.status TEXT — 'active' | 'quarantined'; separates ingested-and-live from
    flagged-for-review records so quarantined content never reaches the vector store
  • customer_segments table — Postgres-first store for segment profiles, replaces full
    vector-store scan on every admin list call
"""
from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── brands: allowed locales list ──────────────────────────────────────
    op.execute(
        "ALTER TABLE brands "
        "ADD COLUMN IF NOT EXISTS allowed_locales TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"
    )
    # Seed existing brands with their source_locale so the column isn't empty
    op.execute(
        "UPDATE brands SET allowed_locales = ARRAY[source_locale] "
        "WHERE array_length(allowed_locales, 1) IS NULL"
    )

    # ── brand_guides: quarantine status ───────────────────────────────────
    op.execute(
        "ALTER TABLE brand_guides "
        "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active' "
        "CHECK (status IN ('active','quarantined'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_brand_guides_status "
        "ON brand_guides(brand_id, status)"
    )

    # ── customer_segments: Postgres-first segment store ───────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id    UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            org_id      UUID NOT NULL REFERENCES orgs(id)  ON DELETE CASCADE,
            locale      TEXT NOT NULL,
            version     TEXT NOT NULL DEFAULT 'v1',
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            age_range   TEXT,
            source_filename TEXT,
            raw_attributes  JSONB NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_segments_brand "
        "ON customer_segments(brand_id, locale)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_customer_segments_brand")
    op.execute("DROP TABLE IF EXISTS customer_segments")
    op.execute("DROP INDEX IF EXISTS idx_brand_guides_status")
    op.execute("ALTER TABLE brand_guides DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE brands DROP COLUMN IF EXISTS allowed_locales")
