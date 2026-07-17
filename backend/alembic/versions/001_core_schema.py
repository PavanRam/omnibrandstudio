"""core schema

Revision ID: 001
Revises:
Create Date: 2026-07-05

Note: no `langgraph_checkpoints` table here by design — LangGraph's
AsyncPostgresSaver manages its own checkpoint schema via `.setup()`,
called during worker/API startup (see pipeline/graph.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')

    # ── orgs ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE orgs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
            tier TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free','paid','enterprise')),
            config JSONB NOT NULL DEFAULT '{}',
            feature_flags JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── brands ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE brands (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            config JSONB NOT NULL DEFAULT '{}',
            source_locale TEXT NOT NULL DEFAULT 'en-US',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_brands_org ON brands(org_id)")

    # ── users ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            totp_secret_enc TEXT,
            roles TEXT[] NOT NULL DEFAULT ARRAY['viewer'],
            brand_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','deactivated','deleted')),
            last_login_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_users_org ON users(org_id)")
    op.execute("CREATE INDEX idx_users_email ON users(email)")

    # ── user_sessions ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE user_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_sessions_token ON user_sessions(token_hash) WHERE revoked_at IS NULL")

    # ── api_keys ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            brand_id UUID REFERENCES brands(id),
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            scopes TEXT[] NOT NULL DEFAULT ARRAY['campaigns:read'],
            last_used_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── campaigns ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE campaigns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id),
            brand_id UUID NOT NULL REFERENCES brands(id),
            created_by UUID REFERENCES users(id),
            brief JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','queued','running','published','failed','cancelled','archived')),
            token_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_campaigns_org ON campaigns(org_id, created_at DESC)")
    op.execute("CREATE INDEX idx_campaigns_brand ON campaigns(brand_id)")
    op.execute("CREATE INDEX idx_campaigns_status ON campaigns(status) WHERE status IN ('queued','running')")

    # ── brand_guides ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE brand_guides (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            locale TEXT NOT NULL,
            version TEXT NOT NULL,
            source_filename TEXT,
            storage_path TEXT,
            indexed_at TIMESTAMPTZ,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            chunk_count INT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_guides_brand ON brand_guides(brand_id, locale, active)")

    # ── terminology_entries ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE terminology_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            source_term TEXT NOT NULL,
            approved_translation TEXT,
            enforcement TEXT NOT NULL DEFAULT 'soft_prefer'
                CHECK (enforcement IN ('hard_block','hard_require','soft_prefer','translation','competitor_block')),
            preferred_alternatives TEXT[],
            locales TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            channels TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            notes TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_terms_brand ON terminology_entries(brand_id, active)")

    # ── brand_claims ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE brand_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            claim_text TEXT NOT NULL,
            category TEXT NOT NULL
                CHECK (category IN ('statistic','certification','feature','pricing','timeline','comparison','regulated')),
            exact_match BOOLEAN NOT NULL DEFAULT FALSE,
            source_reference TEXT,
            valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_claims_brand ON brand_claims(brand_id, active)")
    op.execute("CREATE INDEX idx_claims_expiry ON brand_claims(expires_at) WHERE expires_at IS NOT NULL")

    # ── prompt_registry ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE prompt_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            org_id UUID REFERENCES orgs(id),
            system_prompt TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            variables TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','review','active','deprecated','archived')),
            invocation_count INT NOT NULL DEFAULT 0,
            avg_brand_score NUMERIC(4,2),
            avg_latency_ms INT,
            approval_rate NUMERIC(4,3),
            notes TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(name, version, org_id)
        )
    """)
    op.execute("CREATE UNIQUE INDEX idx_prompt_active ON prompt_registry(name, org_id) WHERE status = 'active'")
    op.execute("CREATE INDEX idx_prompt_name ON prompt_registry(name, status)")

    # ── golden_dataset ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE golden_dataset (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            brand_id UUID REFERENCES brands(id),
            description TEXT,
            brief JSONB NOT NULL,
            expected_content TEXT,
            expected_brand_score NUMERIC(4,2),
            grounding_score_target NUMERIC(4,2),
            known_hallucination_traps JSONB DEFAULT '[]',
            channel TEXT,
            locale TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── prompt_experiments / outcomes ─────────────────────────────────────
    op.execute("""
        CREATE TABLE prompt_experiments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            prompt_name TEXT NOT NULL,
            variant_a TEXT NOT NULL,
            variant_b TEXT NOT NULL,
            split_ratio NUMERIC(3,2) NOT NULL DEFAULT 0.5,
            min_sample_size INT NOT NULL DEFAULT 50,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('draft','running','concluded','archived')),
            winner TEXT CHECK (winner IN ('A','B','none','inconclusive')),
            conclusion_note TEXT,
            org_id UUID REFERENCES orgs(id),
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            concluded_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id)
        )
    """)
    op.execute("""
        CREATE TABLE prompt_experiment_outcomes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            experiment_id UUID NOT NULL REFERENCES prompt_experiments(id),
            campaign_id TEXT NOT NULL,
            variant TEXT NOT NULL CHECK (variant IN ('A','B')),
            prompt_version TEXT NOT NULL,
            channel TEXT,
            locale TEXT,
            brand_score NUMERIC(4,2),
            approved BOOLEAN,
            latency_ms INT,
            cost_usd NUMERIC(10,6),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_exp_outcomes ON prompt_experiment_outcomes(experiment_id, variant)")

    # ── content_variants ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE content_variants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            locale TEXT NOT NULL,
            channel TEXT NOT NULL,
            segment TEXT NOT NULL,
            generated_content TEXT,
            personalized_content TEXT,
            translated_content TEXT,
            final_content TEXT,
            subject_line TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            generation_model TEXT,
            prompt_version TEXT,
            brand_guide_version TEXT,
            translation_engine TEXT,
            back_translation_score NUMERIC(4,3),
            retry_count INT NOT NULL DEFAULT 0,
            failure_reason TEXT,
            reflexion_applied BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_variants_campaign ON content_variants(campaign_id)")
    op.execute("CREATE INDEX idx_variants_status ON content_variants(status)")

    # ── brand_scores ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE brand_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            variant_id UUID NOT NULL REFERENCES content_variants(id) ON DELETE CASCADE,
            judge_model TEXT NOT NULL,
            composite_score NUMERIC(4,2) NOT NULL,
            scores JSONB NOT NULL,
            critical_violations TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            routing_decision TEXT NOT NULL,
            routing_explanation TEXT,
            evaluation_latency_ms INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_brand_scores_variant ON brand_scores(variant_id)")

    # ── aggregated_scores ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE aggregated_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            variant_id UUID NOT NULL REFERENCES content_variants(id) ON DELETE CASCADE UNIQUE,
            judge_scores JSONB NOT NULL,
            weighted_mean NUMERIC(4,2) NOT NULL,
            variance NUMERIC(6,4) NOT NULL,
            consensus_level TEXT NOT NULL,
            any_critical_violation BOOLEAN NOT NULL DEFAULT FALSE,
            critical_violations TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            routing_decision TEXT NOT NULL,
            routing_reason TEXT,
            degraded_mode BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── review_requests ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE review_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            variant_id UUID NOT NULL REFERENCES content_variants(id),
            campaign_id UUID NOT NULL REFERENCES campaigns(id),
            org_id UUID NOT NULL REFERENCES orgs(id),
            brand_id UUID NOT NULL REFERENCES brands(id),
            routing_reason TEXT,
            scores_snapshot JSONB,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected','edited')),
            decision TEXT,
            reviewer_note TEXT,
            edited_content TEXT,
            reviewed_by UUID REFERENCES users(id),
            reviewed_at TIMESTAMPTZ,
            sla_deadline TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_reviews_pending ON review_requests(org_id, brand_id, status) WHERE status = 'pending'")

    # ── publication_receipts ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE publication_receipts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            variant_id UUID NOT NULL REFERENCES content_variants(id),
            campaign_id UUID NOT NULL REFERENCES campaigns(id),
            channel TEXT NOT NULL,
            locale TEXT NOT NULL,
            platform_publication_id TEXT,
            public_url TEXT,
            adapter_used TEXT NOT NULL,
            publish_status TEXT NOT NULL DEFAULT 'pending',
            published_at TIMESTAMPTZ,
            retry_count INT NOT NULL DEFAULT 0,
            error_message TEXT,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_receipts_campaign ON publication_receipts(campaign_id)")

    # ── campaign_cost_attribution ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE campaign_cost_attribution (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES campaigns(id),
            org_id UUID NOT NULL REFERENCES orgs(id),
            brand_id UUID NOT NULL REFERENCES brands(id),
            agent_name TEXT NOT NULL,
            task_id TEXT,
            locale TEXT,
            channel TEXT,
            model_alias TEXT NOT NULL,
            model_resolved TEXT NOT NULL,
            provider TEXT NOT NULL,
            input_tokens INT NOT NULL DEFAULT 0,
            output_tokens INT NOT NULL DEFAULT 0,
            cached_tokens INT NOT NULL DEFAULT 0,
            total_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
            was_cached BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_cost_campaign ON campaign_cost_attribution(campaign_id)")
    op.execute("CREATE INDEX idx_cost_org_month ON campaign_cost_attribution(org_id, created_at)")

    # ── audit_log (partitioned, append-only) ─────────────────────────────
    # Partitioned tables cannot carry FK constraints in PostgreSQL, so
    # entity_id/org_id/brand_id/actor_id here are plain UUID columns.
    op.execute("""
        CREATE TABLE audit_log (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            entity_type TEXT NOT NULL,
            entity_id UUID,
            brand_id UUID,
            org_id UUID,
            action TEXT NOT NULL,
            actor_id UUID,
            actor_type TEXT NOT NULL DEFAULT 'user',
            before_val JSONB,
            after_val JSONB,
            ip_address INET,
            request_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    # Two child partitions so inserts succeed for both the current and
    # prior year (today is 2026-07-05); add future-year partitions in
    # later migrations as needed.
    op.execute("""
        CREATE TABLE audit_log_2025 PARTITION OF audit_log
            FOR VALUES FROM ('2025-01-01') TO ('2026-01-01')
    """)
    op.execute("""
        CREATE TABLE audit_log_2026 PARTITION OF audit_log
            FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')
    """)
    op.execute("CREATE INDEX idx_audit_org ON audit_log(org_id, created_at DESC)")
    op.execute("CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id)")

    # ── audit_log immutability ────────────────────────────────────────────
    # Requires the migration connection to own the table (see ALEMBIC_DSN in
    # .env.example). If the `omnibrand_app` role does not exist yet (e.g.
    # local dev using a single role for everything), these are no-ops.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omnibrand_app') THEN
                REVOKE UPDATE, DELETE ON audit_log FROM omnibrand_app;
                GRANT INSERT ON audit_log TO omnibrand_app;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log_2026")
    op.execute("DROP TABLE IF EXISTS audit_log_2025")
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS campaign_cost_attribution")
    op.execute("DROP TABLE IF EXISTS publication_receipts")
    op.execute("DROP TABLE IF EXISTS review_requests")
    op.execute("DROP TABLE IF EXISTS aggregated_scores")
    op.execute("DROP TABLE IF EXISTS brand_scores")
    op.execute("DROP TABLE IF EXISTS content_variants")
    op.execute("DROP TABLE IF EXISTS prompt_experiment_outcomes")
    op.execute("DROP TABLE IF EXISTS prompt_experiments")
    op.execute("DROP TABLE IF EXISTS golden_dataset")
    op.execute("DROP TABLE IF EXISTS prompt_registry")
    op.execute("DROP TABLE IF EXISTS brand_claims")
    op.execute("DROP TABLE IF EXISTS terminology_entries")
    op.execute("DROP TABLE IF EXISTS brand_guides")
    op.execute("DROP TABLE IF EXISTS campaigns")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS user_sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS brands")
    op.execute("DROP TABLE IF EXISTS orgs")
