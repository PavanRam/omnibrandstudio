"""add translation_checks (content_variants) + evaluation_round (brand_scores)

The full per-check BLEU/semantic-similarity/back-translation-cosine list
(name/value/threshold/passed) is already computed on the in-memory variant
dict during the pipeline run (translation.py::_run_translation_gate) but was
never persisted — only lost after the run completed.

`brand_scores` also has no `evaluation_round` column, even though the
in-memory BrandScore TypedDict always carries one and reflexion causes a
second round of judge scoring for a retried variant — without this column
there is no reliable way to tell which persisted row is the LATEST verdict
for a given (variant, judge_model) pair once more than one round exists
(all rows from one persist_draft_batch call share the same transaction-time
`created_at`, so that can't be used to order rounds either).

Both needed for the new "Run summary" panel (2026-07-27) to show real
per-locale translation reasons and real per-judge scores/reasoning instead
of nothing.

Revision ID: 010
Revises: 009
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content_variants ADD COLUMN translation_checks JSONB")
    op.execute("ALTER TABLE brand_scores ADD COLUMN evaluation_round INT NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE content_variants DROP COLUMN IF EXISTS translation_checks")
    op.execute("ALTER TABLE brand_scores DROP COLUMN IF EXISTS evaluation_round")
