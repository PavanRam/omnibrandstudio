"""Brand profile config — admin-editable entitlement + truthfulness data.

brands.config is an empty JSONB blob until these endpoints start writing to
it. This is the actual data intake_agent reads (pipeline/agents/intake.py)
to enforce channel/locale entitlement and check brief-vs-brand plausibility
— see next_tasks.md items 14/22/42 (2026-07-27). Admin-only: this is org/
brand configuration, not something a regular campaign creator should be
able to change.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.deps import UserContext, get_current_user
from core.database import get_db
from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS
from pipeline.locale_utils import SUPPORTED_LOCALES

router = APIRouter()


def _normalize_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field_name} must be a valid UUID"
        ) from exc


def _require_admin(user: UserContext) -> None:
    if "admin" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")


async def _assert_brand_in_org(conn, user: UserContext, brand_id: str) -> dict:
    result = await conn.execute(
        text("SELECT id, name, config FROM brands WHERE id = :brand_id AND org_id = :org_id"),
        {"brand_id": brand_id, "org_id": user.org_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand not found in your org")
    return dict(row)


class BrandConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = ""
    key_claims: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=list)


class CreateBrandRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_locale: str = "en-US"


@router.get("/{brand_id}/entitlements")
async def get_brand_entitlements(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Channels and locales this brand is entitled to use — readable by any
    authenticated user (not admin-only) so the campaign-creation chat UI can
    populate its inline channel/locale pickers without requiring admin access.

    Returns the brand's explicitly configured allow-lists when set, falling
    back to every globally-supported value (same permissive default intake_agent
    uses — see pipeline/agents/intake.py::_load_brand_profile).
    """
    normalized_id = _normalize_uuid(brand_id, "brand_id")
    async with get_db() as conn:
        result = await conn.execute(
            text("SELECT id, config FROM brands WHERE id = :brand_id AND org_id = :org_id"),
            {"brand_id": normalized_id, "org_id": user.org_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brand not found")

    config = row["config"] or {}
    all_channels = sorted(DEFAULT_CHANNEL_CONSTRAINTS.keys())
    # Fallback locale list = source locale short code + the 4 translation-supported
    # short codes. Matches exactly what SUPPORTED_LOCALES + SOURCE_LOCALE_BASE
    # contains — never the full _SHORT_CODE_TO_LOCALE set (which has 11 entries
    # including languages the translation_agent can't actually handle).
    from pipeline.locale_utils import SOURCE_LOCALE_BASE  # noqa: PLC0415
    all_supported_locales = sorted({SOURCE_LOCALE_BASE} | SUPPORTED_LOCALES)

    brand_channels = config.get("channels") or all_channels
    # config["locales"] is either:
    #   - a non-empty list of short codes the admin saved  → use those
    #   - [] or missing (no restriction set)               → fall back to all supported
    configured_locales = config.get("locales") or []
    brand_locales = configured_locales if configured_locales else all_supported_locales

    return {
        "brand_id": normalized_id,
        "channels": sorted(brand_channels),
        "locales": sorted(brand_locales),
    }


@router.get("")
async def list_brands(user: Annotated[UserContext, Depends(get_current_user)]) -> dict[str, Any]:
    """Brands the caller can see — scoped the same way `_assert_brand_access`
    (knowledge.py) already scopes everything else: an explicit `brand_ids`
    list restricts to exactly those brands (used by the "pick a brand before
    starting a conversation" flow for a multi-brand user); an org-scoped
    user/admin with no explicit brand_ids sees every brand in the org.
    Not admin-gated — any authenticated user needs this to see their own
    brand(s), unlike create/config which are admin-only."""
    async with get_db() as conn:
        if user.brand_ids:
            result = await conn.execute(
                text("SELECT id, name, source_locale FROM brands WHERE id = ANY(:brand_ids) ORDER BY name"),
                {"brand_ids": user.brand_ids},
            )
        else:
            result = await conn.execute(
                text("SELECT id, name, source_locale FROM brands WHERE org_id = :org_id ORDER BY name"),
                {"org_id": user.org_id},
            )
        rows = result.mappings().all()
    return {"brands": [dict(row) for row in rows]}


@router.post("")
async def create_brand(
    body: CreateBrandRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_admin(user)
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO brands (org_id, name, source_locale)
                VALUES (CAST(:org_id AS UUID), :name, :source_locale)
                RETURNING id, name, source_locale
                """
            ),
            {"org_id": user.org_id, "name": body.name.strip(), "source_locale": body.source_locale},
        )
        row = result.mappings().first()
    return dict(row)


@router.get("/{brand_id}/config")
async def get_brand_config(
    brand_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_admin(user)
    normalized_id = _normalize_uuid(brand_id, "brand_id")
    async with get_db() as conn:
        brand = await _assert_brand_in_org(conn, user, normalized_id)

    config = brand.get("config") or {}
    return {
        "brand_id": brand["id"],
        "brand_name": brand["name"],
        "industry": config.get("industry", ""),
        "key_claims": config.get("key_claims", []),
        # Explicit configured allow-list, or None if the brand hasn't set one
        # yet (falls back to every globally-supported value at intake time —
        # see pipeline/agents/intake.py::_load_brand_profile).
        "channels": config.get("channels"),
        "locales": config.get("locales"),
        "available_channels": sorted(DEFAULT_CHANNEL_CONSTRAINTS.keys()),
        "available_locales": sorted(SUPPORTED_LOCALES),
    }


@router.patch("/{brand_id}/config")
async def update_brand_config(
    brand_id: str,
    body: BrandConfigRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_admin(user)
    normalized_id = _normalize_uuid(brand_id, "brand_id")

    unsupported_channels = [c for c in body.channels if c not in DEFAULT_CHANNEL_CONSTRAINTS]
    if unsupported_channels:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unsupported channel(s): {unsupported_channels}"
        )
    unsupported_locales = [loc for loc in body.locales if loc not in SUPPORTED_LOCALES]
    if unsupported_locales:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unsupported locale(s): {unsupported_locales}"
        )

    async with get_db() as conn:
        await _assert_brand_in_org(conn, user, normalized_id)

        new_config = {
            "industry": body.industry.strip(),
            "key_claims": [c.strip() for c in body.key_claims if c.strip()],
            # Empty list means "no restriction configured" downstream (intake
            # falls back to every globally-supported value) — store as an
            # empty list rather than omitting the key, so a brand that used
            # to have an explicit allow-list can be reset back to "allow all"
            # deliberately, not just by accident.
            "channels": [c for c in body.channels if c],
            "locales": [loc for loc in body.locales if loc],
        }
        await conn.execute(
            text("UPDATE brands SET name = :name, config = CAST(:config AS jsonb) WHERE id = :brand_id"),
            {"name": body.name.strip(), "config": json.dumps(new_config), "brand_id": normalized_id},
        )

    return {
        "brand_id": normalized_id,
        "name": body.name.strip(),
        "industry": new_config["industry"],
        "key_claims": new_config["key_claims"],
        "channels": new_config["channels"],
        "locales": new_config["locales"],
    }
