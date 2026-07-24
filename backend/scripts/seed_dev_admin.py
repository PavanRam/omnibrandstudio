#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand",
)
DEFAULT_ORG_ID = os.getenv("DEV_ADMIN_ORG_ID", "00000000-0000-0000-0000-000000000001")
DEFAULT_BRAND_ID = os.getenv("DEV_ADMIN_BRAND_ID", "00000000-0000-0000-0000-000000000002")
DEFAULT_EMAIL = os.getenv("DEV_ADMIN_EMAIL", "admin@omnibrand.local")
DEFAULT_PASSWORD = os.getenv("DEV_ADMIN_PASSWORD", "")


def hash_password(raw_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(raw_password.encode("utf-8"), salt).decode("utf-8")


async def seed_admin(email: str, password: str, org_id: str, brand_id: str) -> None:
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("Invalid email")

    password_hash = hash_password(password)
    engine = create_async_engine(POSTGRES_DSN, echo=False)

    async with engine.begin() as conn:
        org_exists = await conn.execute(
            text("SELECT 1 FROM orgs WHERE id = CAST(:org_id AS UUID)"),
            {"org_id": org_id},
        )
        if org_exists.first() is None:
            raise RuntimeError(f"Org not found: {org_id}. Run seed/provisioning first.")

        brand_exists = await conn.execute(
            text("SELECT 1 FROM brands WHERE id = CAST(:brand_id AS UUID)"),
            {"brand_id": brand_id},
        )
        if brand_exists.first() is None:
            raise RuntimeError(f"Brand not found: {brand_id}. Run seed/provisioning first.")

        existing = await conn.execute(
            text(
                """
                SELECT id
                FROM users
                WHERE lower(email) = :email
                LIMIT 1
                """
            ),
            {"email": email},
        )
        row = existing.mappings().first()

        if row is None:
            created = await conn.execute(
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
                    RETURNING id
                    """
                ),
                {
                    "org_id": org_id,
                    "email": email,
                    "password_hash": password_hash,
                    "brand_id": brand_id,
                },
            )
            user_id = str(created.mappings().one()["id"])
            print(f"Created dev admin user: {email} ({user_id})")
        else:
            await conn.execute(
                text(
                    """
                    UPDATE users
                    SET org_id = CAST(:org_id AS UUID),
                        password_hash = :password_hash,
                        roles = ARRAY['admin']::TEXT[],
                        brand_ids = ARRAY[CAST(:brand_id AS UUID)]::UUID[],
                        status = 'active'
                    WHERE id = CAST(:user_id AS UUID)
                    """
                ),
                {
                    "org_id": org_id,
                    "password_hash": password_hash,
                    "brand_id": brand_id,
                    "user_id": str(row["id"]),
                },
            )
            print(f"Updated dev admin user: {email} ({row['id']})")

    await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed or update a local dev admin user")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--brand-id", default=DEFAULT_BRAND_ID)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.password or len(args.password) < 8:
        raise SystemExit(
            "Provide --password (min 8 chars) or set DEV_ADMIN_PASSWORD env var before running."
        )
    asyncio.run(seed_admin(args.email, args.password, args.org_id, args.brand_id))


if __name__ == "__main__":
    main()
