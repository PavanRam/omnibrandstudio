"""Golden/silver dataset API — tenant-isolated evaluation-set management.

Mounted under ``/knowledge`` alongside the brand-guide endpoints. Every route
resolves ``org_id`` from the authenticated caller and re-checks brand access
via the same ``_assert_brand_access`` guard used for brand guides, so a caller
can only read or mutate its own tenant's datasets.
"""
from typing import Annotated, Any

from core.database import get_db
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from services import golden_dataset_service as svc

from api.deps import UserContext, get_current_user
from api.routers.knowledge import _assert_brand_access

router = APIRouter()


class OpenSetRequest(BaseModel):
    brand_id: str
    locale: str = "en-US"
    guide_version: str | None = None
    source: str = Field(default="llm_generated", pattern="^(llm_generated|human_curated)$")


class BulkInsertRequest(BaseModel):
    brand_id: str
    set_id: str
    source: str = Field(default="llm_generated", pattern="^(llm_generated|human_curated)$")
    status: str = Field(default="silver", pattern="^(silver|golden)$")
    examples: list[dict[str, Any]]


class UpdateExampleRequest(BaseModel):
    description: str | None = None
    expected_content: str | None = None
    expected_brand_score: float | None = None
    status: str | None = Field(None, pattern="^(silver|golden)$")
    known_hallucination_traps: list[str] | None = None


class AddExampleRequest(BaseModel):
    brand_id: str
    set_id: str
    channel: str
    description: str
    brief: dict[str, Any]
    expected_content: str
    expected_brand_score: float
    status: str = Field(default="silver", pattern="^(silver|golden)$")
    known_hallucination_traps: list[str] | None = None
    locale: str | None = None


class PromoteRequest(BaseModel):
    brand_id: str


@router.post("/golden-dataset/sets", status_code=status.HTTP_201_CREATED)
async def open_draft_set(
    body: OpenSetRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, body.brand_id)
        set_id = await svc.open_draft_set(
            conn,
            org_id=user.org_id,
            brand_id=body.brand_id,
            locale=body.locale,
            guide_version=body.guide_version,
            source=body.source,
            created_by=user.user_id,
        )
        await conn.commit()
    return {"status": "created", "set_id": set_id}


@router.get("/golden-dataset/sets/{brand_id}")
async def list_sets(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
    limit: int = 50,
    offset: int = 0,
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        sets = await svc.list_sets(conn, org_id=user.org_id, brand_id=brand_id,
                                    limit=limit, offset=offset)
    return {"brand_id": brand_id, "count": len(sets), "items": sets}


@router.post("/golden-dataset/sets/{brand_id}/backfill")
async def backfill_sets(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Explicitly backfill golden-dataset sets from existing brand guide versions.

    Previously this happened implicitly on the first GET; it is now a deliberate
    admin action so GET never writes to the database.
    """
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        inserted = await svc.backfill_sets_from_guide_versions(
            conn,
            org_id=user.org_id,
            brand_id=brand_id,
            created_by=user.user_id,
        )
        if inserted:
            await conn.commit()
    return {"brand_id": brand_id, "sets_created": inserted}


@router.post("/golden-dataset/sets/{set_id}/activate")
async def activate_set(
    set_id: str,
    body: PromoteRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, body.brand_id)
        try:
            await svc.activate_set(
                conn,
                org_id=user.org_id,
                brand_id=body.brand_id,
                set_id=set_id,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "activated", "set_id": set_id}


@router.delete("/golden-dataset/sets/{set_id}")
async def delete_set(
    set_id: str,
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        try:
            await svc.delete_set(
                conn,
                org_id=user.org_id,
                brand_id=brand_id,
                set_id=set_id,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"status": "deleted", "set_id": set_id}


@router.post("/golden-dataset", status_code=status.HTTP_201_CREATED)
async def bulk_insert_examples(
    body: BulkInsertRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, body.brand_id)
        try:
            count = await svc.bulk_insert(
                conn,
                org_id=user.org_id,
                brand_id=body.brand_id,
                set_id=body.set_id,
                examples=body.examples,
                source=body.source,
                status=body.status,
                created_by=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "inserted", "count": count}


@router.get("/golden-dataset/{brand_id}")
async def list_examples(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
    status_filter: str | None = None,
    set_id: str | None = None,
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        items = await svc.list_examples(
            conn,
            org_id=user.org_id,
            brand_id=brand_id,
            status=status_filter,
            set_id=set_id,
        )
    return {"brand_id": brand_id, "count": len(items), "items": items}


@router.post("/golden-dataset/{example_id}/promote")
async def promote_example(
    example_id: str,
    body: PromoteRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, body.brand_id)
        try:
            await svc.promote_to_golden(
                conn,
                org_id=user.org_id,
                brand_id=body.brand_id,
                example_id=example_id,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "promoted", "example_id": example_id}


@router.delete("/golden-dataset/{example_id}")
async def delete_example(
    example_id: str,
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        try:
            await svc.delete_example(
                conn,
                org_id=user.org_id,
                brand_id=brand_id,
                example_id=example_id,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "deleted", "example_id": example_id}


@router.patch("/golden-dataset/example/{example_id}")
async def update_example(
    example_id: str,
    brand_id: str,
    body: UpdateExampleRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Update a golden dataset example. Only provided fields are updated."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, brand_id)
        try:
            updated = await svc.update_example(
                conn,
                org_id=user.org_id,
                brand_id=brand_id,
                example_id=example_id,
                description=body.description,
                expected_content=body.expected_content,
                expected_brand_score=body.expected_brand_score,
                status=body.status,
                known_hallucination_traps=body.known_hallucination_traps,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "updated", "example_id": example_id, "example": updated}


@router.post("/golden-dataset/example")
async def add_example(
    body: AddExampleRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Add a single example to a golden dataset set."""
    async with get_db() as conn:
        await _assert_brand_access(conn, user, body.brand_id)
        try:
            example_id = await svc.add_example(
                conn,
                org_id=user.org_id,
                brand_id=body.brand_id,
                set_id=body.set_id,
                channel=body.channel,
                description=body.description,
                brief=body.brief,
                expected_content=body.expected_content,
                expected_brand_score=body.expected_brand_score,
                status=body.status,
                source="human_curated",
                known_hallucination_traps=body.known_hallucination_traps,
                locale=body.locale,
                actor_id=user.user_id,
            )
            await conn.commit()
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"status": "created", "example_id": example_id}
