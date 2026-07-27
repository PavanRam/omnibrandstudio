from typing import Annotated

from core.database import get_db
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from services import golden_dataset_service
from services.rag import get_vector_store
from services.rag.ingest import ingest_brand_guide, ingest_customer_segments, list_customer_segments
from sqlalchemy import text

from api.deps import UserContext, get_current_user

router = APIRouter()


async def _assert_brand_access(conn, user: UserContext, brand_id: str) -> None:
    # API keys and scoped JWTs must match explicit brand grants.
    if user.brand_ids and brand_id not in user.brand_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Brand not in caller scope")

    # For org-scoped users without explicit brand_ids, enforce org->brand ownership.
    if not user.brand_ids:
        result = await conn.execute(
            text("SELECT 1 FROM brands WHERE id = :brand_id AND org_id = :org_id"),
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
) -> dict:
    """List known brand-guide versions for a brand from Postgres metadata."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        if include_inactive:
            query = text(
                "SELECT id, locale, version, source_filename, indexed_at, active, chunk_count, created_at "
                "FROM brand_guides WHERE brand_id = :brand_id "
                "ORDER BY created_at DESC"
            )
        else:
            query = text(
                "SELECT id, locale, version, source_filename, indexed_at, active, chunk_count, created_at "
                "FROM brand_guides WHERE brand_id = :brand_id AND active = TRUE "
                "ORDER BY created_at DESC"
            )
        params = {"brand_id": brand_id}

        try:
            result = await conn.execute(query, params)
            rows = [dict(row) for row in result.mappings().all()]
        except Exception as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

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
            brand_id=brand_id,
            file_bytes=file_bytes,
            filename=segment_file.filename or "uploaded.segments",
            locale=locale,
            version=version,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return {
        "status": "indexed",
        **result,
    }


@router.get("/segments/{brand_id}/options")
async def list_segment_options(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Distinct segment/persona labels for the structured brief-input
    dropdown (next_tasks.md item 23, 2026-07-27) — reads the REAL seeded
    customer-segment data (~4,426 chunked rows, 5 distinct `persona` values
    as seeded), not the 3-persona placeholder list.

    Deliberately does NOT reuse list_customer_segments/list_segments below
    — those filter on content_type="segment_profile" (what the manual
    upload path, ingest_customer_segments, writes), while the SEEDED demo
    data was written by a different path (ingest_seed_datasets ->
    _build_points) with content_type="segments". Querying the "segment_profile"
    filter against the seeded data returns nothing at all. This endpoint
    queries the collection directly with the filter that actually matches
    the seeded rows.
    """
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)

    collection = f"brand_{brand_id}_segments"
    docs = await get_vector_store().get_documents(
        collection=collection,
        filters={"brand_id": brand_id},
        limit=5000,
    )
    options = sorted(
        {str(doc.metadata.get("persona")).strip() for doc in docs if doc.metadata.get("persona")}
    )
    return {"brand_id": brand_id, "options": options}


@router.get("/segments/{brand_id}")
async def list_segments(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
    locale: str,
    version: str | None = None,
    limit: int = 50,
) -> dict:
    """List indexed customer-segment documents for a brand/locale."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)

    items = await list_customer_segments(
        brand_id=brand_id,
        locale=locale,
        version=version,
        limit=limit,
    )
    return {
        "brand_id": brand_id,
        "locale": locale,
        "version": version,
        "count": len(items),
        "items": items,
    }
