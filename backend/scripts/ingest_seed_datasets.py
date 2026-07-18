from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import shutil

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from services.rag.ingest import ingest_seed_datasets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest del_branch-style JSON/CSV datasets into RAG collections")
    parser.add_argument("--seed-dir", required=True, help="Path to seed data directory")
    parser.add_argument("--org-id", required=True, help="Org ID that must own the target brand")
    parser.add_argument("--brand-id", required=True, help="Brand ID to scope collections")
    parser.add_argument("--locale", default="en-US", help="Locale for metadata")
    parser.add_argument("--version", default="seed-v1", help="Version tag for ingested points")
    parser.add_argument(
        "--copy-from",
        default="",
        help="Optional source directory to copy expected base files from before ingest",
    )
    return parser.parse_args()


async def _assert_brand_in_org(conn, *, brand_id: str, org_id: str) -> None:
    result = await conn.execute(
        text("SELECT 1 FROM brands WHERE id = :brand_id AND org_id = :org_id"),
        {"brand_id": brand_id, "org_id": org_id},
    )
    if result.mappings().first() is None:
        raise PermissionError(f"Brand {brand_id} is not owned by org {org_id}")


def _copy_base_files(copy_from: Path, seed_dir: Path) -> None:
    if not copy_from.exists():
        raise FileNotFoundError(f"copy-from path does not exist: {copy_from}")

    seed_dir.mkdir(parents=True, exist_ok=True)
    expected = [
        "customer_segments.csv",
        "campaigns_clean.csv",
        "social_media_ads_clean.csv",
        "sentiment140_clean.csv",
        "brand_guidelines",
    ]
    for name in expected:
        src = copy_from / name
        dst = seed_dir / name
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


async def _run(args: argparse.Namespace) -> None:
    seed_dir = Path(args.seed_dir).resolve()
    if args.copy_from:
        _copy_base_files(Path(args.copy_from).resolve(), seed_dir)

    if not seed_dir.exists():
        raise FileNotFoundError(f"Seed directory not found: {seed_dir}")

    engine = create_async_engine(settings.POSTGRES_DSN, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await _assert_brand_in_org(conn, brand_id=args.brand_id, org_id=args.org_id)
            counts = await ingest_seed_datasets(
                db=conn,
                seed_dir=seed_dir,
                brand_id=args.brand_id,
                locale=args.locale,
                version=args.version,
            )
        print(f"Ingestion complete: {counts}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run(parse_args()))
