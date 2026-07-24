from typing import Annotated

from core.database import get_db
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from services import golden_dataset_service
from services.rag.ingest import (
    ingest_brand_guide,
    ingest_customer_segments,
    list_brand_guides_from_store,
    list_customer_segments,
)

from api.deps import UserContext, get_current_user


class AllowedLocalesUpdate(BaseModel):
    allowed_locales: list[str]

router = APIRouter()


async def _assert_brand_access(conn, user: UserContext, brand_id: str) -> None:
    # API keys and scoped JWTs must match explicit brand grants.
    if user.brand_ids and brand_id not in user.brand_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brand not in caller scope")

    # For org-scoped users without explicit brand_ids, enforce org->brand ownership.
    if not user.brand_ids:
        result = await conn.execute(
            text("SELECT 1 FROM brands WHERE id = CAST(:brand_id AS UUID) AND org_id = CAST(:org_id AS UUID)"),
            {"brand_id": brand_id, "org_id": user.org_id},
        )
        if result.mappings().first() is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Brand not accessible in caller org")


@router.post("/brand-guides")
async def upload_brand_guide(
    brand_id: Annotated[str, Form(...)],
    locale: Annotated[str, Form(...)],
    version: Annotated[str, Form(...)],
    guide_file: Annotated[UploadFile, File(...)],
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Ingest a brand guide document into the configured vector backend.

    This endpoint is the canonical runtime entrypoint for RAG ingestion.
    It extracts text, chunks content, indexes vectors and updates brand_guide
    metadata version state for the provided brand/locale.
    """
    file_bytes = await guide_file.read()
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        result = await ingest_brand_guide(
            db=conn,
            brand_id=brand_id,
            file_bytes=file_bytes,
            filename=guide_file.filename or "uploaded.guide",
            locale=locale,
            version=version,
        )
        # Open a draft golden-dataset set pinned to this guide version so
        # evaluation examples can be generated/curated against it (no LLM spend
        # here — generation is a separate, explicit step).
        set_id = await golden_dataset_service.open_draft_set(
            conn,
            org_id=user.org_id,
            brand_id=brand_id,
            locale=locale,
            guide_version=version,
            source="llm_generated",
            created_by=user.user_id,
        )
        await conn.commit()
    return {
        "status": "indexed",
        "golden_dataset_set_id": set_id,
        **result,
    }


@router.get("/brand-guides/{brand_id}")
async def list_brand_guides(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
    include_inactive: bool = False,
    include_quarantined: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List known brand-guide versions for a brand from Postgres metadata."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        conditions = ["brand_id = CAST(:brand_id AS UUID)"]
        if not include_quarantined:
            conditions.append("status != 'quarantined'")
        if not include_inactive:
            conditions.append("active = TRUE")
        where = " AND ".join(conditions)
        query = (
            "SELECT id, locale, version, source_filename, indexed_at, active, chunk_count, status, created_at "
            f"FROM brand_guides WHERE {where} "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        params = {"brand_id": brand_id, "limit": limit, "offset": offset}

        try:
            result = await conn.execute(text(query), params)
            rows = [dict(row) for row in result.mappings().all()]
        except Exception as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    if not rows:
        rows = await list_brand_guides_from_store(brand_id=brand_id)

    return {
        "brand_id": brand_id,
        "count": len(rows),
        "items": rows,
    }


@router.post("/segments")
async def upload_customer_segments(
    brand_id: Annotated[str, Form(...)],
    locale: Annotated[str, Form(...)],
    version: Annotated[str, Form(...)],
    segment_file: Annotated[UploadFile, File(...)],
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Ingest customer-segment records into brand-scoped segments collection."""
    file_bytes = await segment_file.read()
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        try:
            result = await ingest_customer_segments(
                db=conn,
                brand_id=brand_id,
                org_id=user.org_id,
                file_bytes=file_bytes,
                filename=segment_file.filename or "uploaded.segments",
                locale=locale,
                version=version,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return result


@router.get("/segments/{brand_id}")
async def list_segments(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
    locale: str,
    version: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List indexed customer-segment documents for a brand/locale (Postgres-first)."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        items = await list_customer_segments(
            brand_id=brand_id,
            locale=locale,
            version=version,
            limit=limit,
            offset=offset,
            db=conn,
        )
    return {
        "brand_id": brand_id,
        "locale": locale,
        "version": version,
        "count": len(items),
        "items": items,
    }


@router.get("/brands/{brand_id}/allowed-locales")
async def get_allowed_locales(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Return the list of allowed locales configured for this brand."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        result = await conn.execute(
            text("SELECT allowed_locales, source_locale FROM brands WHERE id = CAST(:id AS UUID)"),
            {"id": brand_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand not found")
    locales = list(row["allowed_locales"] or [row["source_locale"]])
    return {"brand_id": brand_id, "allowed_locales": locales}


@router.patch("/brands/{brand_id}/allowed-locales")
async def set_allowed_locales(
    brand_id: str,
    body: AllowedLocalesUpdate,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Replace the allowed_locales list for this brand (admin only)."""
    if "admin" not in (user.roles or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        await conn.execute(
            text(
                "UPDATE brands SET allowed_locales = CAST(:locales AS TEXT[]) "
                "WHERE id = CAST(:id AS UUID)"
            ),
            {"locales": body.allowed_locales, "id": brand_id},
        )
        await conn.commit()
    return {"brand_id": brand_id, "allowed_locales": body.allowed_locales}
