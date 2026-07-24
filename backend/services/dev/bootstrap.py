from __future__ import annotations

import logging

import bcrypt
from core.config import settings
from core.database import get_db
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_dev_bootstrap() -> None:
    """Idempotently ensure baseline org/brand/admin exists for local development."""
    if settings.APP_ENV.lower() == "production" or not settings.DEV_BOOTSTRAP_ADMIN_ENABLED:
        return

    password = settings.DEV_ADMIN_PASSWORD.strip()
    email = settings.DEV_ADMIN_EMAIL.strip().lower()
    if len(password) < 8:
        logger.warning("Skipping dev bootstrap: DEV_ADMIN_PASSWORD must be at least 8 chars")
        return

    async with get_db() as conn:
        tables = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('orgs', 'brands', 'users')
                """
            )
        )
        found = {row[0] for row in tables.fetchall()}
        required = {"orgs", "brands", "users"}
        missing = required - found
        if missing:
            logger.warning(
                "Skipping dev bootstrap: missing tables %s (run migrations first)",
                ", ".join(sorted(missing)),
            )
            return

        await conn.execute(
            text(
                """
                INSERT INTO orgs (id, name, slug, status, tier, config, feature_flags)
                VALUES (
                    CAST(:org_id AS UUID),
                    'Demo Org',
                    'demo-org',
                    'active',
                    'free',
                    '{}'::jsonb,
                    '{}'::jsonb
                )
                ON CONFLICT (id) DO UPDATE
                SET name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    status = 'active',
                    tier = 'free',
                    updated_at = NOW()
                """
            ),
            {"org_id": settings.DEV_ADMIN_ORG_ID},
        )

        await conn.execute(
            text(
                """
                INSERT INTO brands (id, org_id, name, config, source_locale, status)
                VALUES (
                    CAST(:brand_id AS UUID),
                    CAST(:org_id AS UUID),
                    'Demo Brand',
                    '{}'::jsonb,
                    'en-US',
                    'active'
                )
                ON CONFLICT (id) DO UPDATE
                SET org_id = EXCLUDED.org_id,
                    name = EXCLUDED.name,
                    status = 'active'
                """
            ),
            {
                "org_id": settings.DEV_ADMIN_ORG_ID,
                "brand_id": settings.DEV_ADMIN_BRAND_ID,
            },
        )

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        await conn.execute(
            text(
                """
                INSERT INTO users (org_id, email, password_hash, roles, brand_ids, status)
                VALUES (
                    CAST(:org_id AS UUID),
                    :email,
                    :password_hash,
                    ARRAY['admin']::TEXT[],
                    ARRAY[CAST(:brand_id AS UUID)]::UUID[],
                    'active'
                )
                ON CONFLICT (email) DO UPDATE
                SET org_id = EXCLUDED.org_id,
                    password_hash = EXCLUDED.password_hash,
                    roles = ARRAY['admin']::TEXT[],
                    brand_ids = ARRAY[CAST(:brand_id AS UUID)]::UUID[],
                    status = 'active'
                """
            ),
            {
                "org_id": settings.DEV_ADMIN_ORG_ID,
                "brand_id": settings.DEV_ADMIN_BRAND_ID,
                "email": email,
                "password_hash": password_hash,
            },
        )

    logger.info("Dev bootstrap complete for %s", email)
