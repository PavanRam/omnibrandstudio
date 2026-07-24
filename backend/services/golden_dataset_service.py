"""Golden/silver dataset service — tenant-isolated CRUD + set lifecycle.

Every method is scoped by ``org_id`` AND ``brand_id`` (never brand alone) so a
caller can only ever touch its own tenant's evaluation data. All mutations are
recorded through ``write_audit`` under the ``golden_dataset`` entity type.

Dataset model:
  • a *set* (``golden_dataset_set``) is a versioned collection pinned to a brand
    guide version, moving draft → active → archived (one active per
    org+brand+locale);
  • an *example* (``golden_dataset``) belongs to a set and is either ``silver``
    (machine-generated, unreviewed) or ``golden`` (human-approved).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.audit_service import write_audit
from services.rag.ingest import list_brand_guides_from_store


async def open_draft_set(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    locale: str,
    guide_version: str | None,
    source: str = "llm_generated",
    created_by: str | None = None,
) -> str:
    """Create a new draft set for a brand guide version and return its id."""
    result = await conn.execute(
        text(
            """
            INSERT INTO golden_dataset_set
                (org_id, brand_id, locale, guide_version, status, source, created_by)
            VALUES
                (:org_id, :brand_id, :locale, :guide_version, 'draft', :source, :created_by)
            RETURNING id
            """
        ),
        {
            "org_id": org_id,
            "brand_id": brand_id,
            "locale": locale,
            "guide_version": guide_version,
            "source": source,
            "created_by": created_by,
        },
    )
    set_id = str(result.scalar_one())
    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="set_opened",
        actor_id=created_by,
        entity_id=set_id,
        brand_id=brand_id,
        org_id=org_id,
        after_val={"locale": locale, "guide_version": guide_version, "source": source},
    )
    return set_id


async def list_sets(
    conn: AsyncConnection, *, org_id: str, brand_id: str,
    limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT s.id, s.locale, s.guide_version, s.status, s.source,
                   s.created_at, s.activated_at,
                   COUNT(gd.id) AS example_count,
                   COUNT(gd.id) FILTER (WHERE gd.status = 'golden') AS golden_count
            FROM golden_dataset_set s
            LEFT JOIN golden_dataset gd ON gd.set_id = s.id
            WHERE s.org_id = :org_id AND s.brand_id = :brand_id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"org_id": org_id, "brand_id": brand_id, "limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings().all()]


async def backfill_sets_from_guide_versions(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    created_by: str | None = None,
) -> int:
    existing_sets = await list_sets(conn, org_id=org_id, brand_id=brand_id)
    existing_keys = {
        (str(item.get("locale") or ""), str(item.get("guide_version") or ""))
        for item in existing_sets
    }

    result = await conn.execute(
        text(
            """
            SELECT DISTINCT bg.locale, bg.version
            FROM brand_guides bg
            JOIN brands b ON b.id = bg.brand_id
            WHERE bg.brand_id = CAST(:brand_id AS UUID)
              AND b.org_id = CAST(:org_id AS UUID)
              AND bg.active = TRUE
            ORDER BY bg.locale, bg.version
            """
        ),
        {"org_id": org_id, "brand_id": brand_id},
    )
    guide_rows = [dict(row) for row in result.mappings().all()]

    if not guide_rows:
        guide_rows = await list_brand_guides_from_store(brand_id=brand_id)

    inserted = 0
    seen_keys: set[tuple[str, str]] = set()
    for row in guide_rows:
        locale = str(row.get("locale") or "").strip()
        guide_version = str(row.get("version") or "").strip()
        if not locale or not guide_version:
            continue

        key = (locale, guide_version)
        if key in seen_keys or key in existing_keys:
            continue

        await open_draft_set(
            conn,
            org_id=org_id,
            brand_id=brand_id,
            locale=locale,
            guide_version=guide_version,
            source="llm_generated",
            created_by=created_by,
        )
        seen_keys.add(key)
        inserted += 1

    return inserted


async def activate_set(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    set_id: str,
    actor_id: str | None = None,
) -> None:
    """Promote a draft set to active, archiving the prior active set for the
    same (org, brand, locale). Enforced atomically by the partial unique index."""
    result = await conn.execute(
        text(
            """
            SELECT locale, status FROM golden_dataset_set
            WHERE id = :set_id AND org_id = :org_id AND brand_id = :brand_id
            """
        ),
        {"set_id": set_id, "org_id": org_id, "brand_id": brand_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError("set not found in tenant scope")

    await conn.execute(
        text(
            """
            UPDATE golden_dataset_set SET status = 'archived'
            WHERE org_id = :org_id AND brand_id = :brand_id
              AND locale = :locale AND status = 'active' AND id != :set_id
            """
        ),
        {"org_id": org_id, "brand_id": brand_id, "locale": row["locale"], "set_id": set_id},
    )
    await conn.execute(
        text(
            """
            UPDATE golden_dataset_set
            SET status = 'active', activated_at = NOW()
            WHERE id = :set_id AND org_id = :org_id AND brand_id = :brand_id
            """
        ),
        {"set_id": set_id, "org_id": org_id, "brand_id": brand_id},
    )
    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="set_activated",
        actor_id=actor_id,
        entity_id=set_id,
        brand_id=brand_id,
        org_id=org_id,
    )


async def bulk_insert(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    set_id: str,
    examples: list[dict[str, Any]],
    source: str = "llm_generated",
    status: str = "silver",
    created_by: str | None = None,
) -> int:
    """Insert evaluation examples into a set. Returns the number inserted."""
    # Guard: the set must belong to this tenant.
    guard = await conn.execute(
        text(
            "SELECT 1 FROM golden_dataset_set "
            "WHERE id = :set_id AND org_id = :org_id AND brand_id = :brand_id"
        ),
        {"set_id": set_id, "org_id": org_id, "brand_id": brand_id},
    )
    if guard.first() is None:
        raise ValueError("set not found in tenant scope")

    inserted = 0
    for ex in examples:
        await conn.execute(
            text(
                """
                INSERT INTO golden_dataset
                    (org_id, brand_id, set_id, status, source, created_by,
                     description, brief, expected_content, expected_brand_score,
                     grounding_score_target, known_hallucination_traps, channel, locale)
                VALUES
                    (:org_id, :brand_id, :set_id, :status, :source, :created_by,
                     :description, :brief, :expected_content, :expected_brand_score,
                     :grounding_score_target, :known_hallucination_traps, :channel, :locale)
                """
            ),
            {
                "org_id": org_id,
                "brand_id": brand_id,
                "set_id": set_id,
                "status": status,
                "source": source,
                "created_by": created_by,
                "description": ex.get("description"),
                "brief": json.dumps(ex.get("brief") or {}),
                "expected_content": ex.get("expected_content"),
                "expected_brand_score": ex.get("expected_brand_score"),
                "grounding_score_target": ex.get("grounding_score_target"),
                "known_hallucination_traps": json.dumps(
                    ex.get("known_hallucination_traps") or []
                ),
                "channel": ex.get("channel"),
                "locale": ex.get("locale"),
            },
        )
        inserted += 1

    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="examples_inserted",
        actor_id=created_by,
        entity_id=set_id,
        brand_id=brand_id,
        org_id=org_id,
        after_val={"count": inserted, "status": status, "source": source},
    )
    return inserted


async def list_examples(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    status: str | None = None,
    set_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["org_id = :org_id", "brand_id = :brand_id"]
    params: dict[str, Any] = {"org_id": org_id, "brand_id": brand_id}
    if status is not None:
        clauses.append("status = :status")
        params["status"] = status
    if set_id is not None:
        clauses.append("set_id = :set_id")
        params["set_id"] = set_id
    where = " AND ".join(clauses)
    result = await conn.execute(
        text(
            f"""
            SELECT id, set_id, status, source, description, brief, expected_content,
                   expected_brand_score, grounding_score_target,
                   known_hallucination_traps, channel, locale, created_at
            FROM golden_dataset
            WHERE {where}
            ORDER BY created_at DESC
            """
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def promote_to_golden(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    example_id: str,
    actor_id: str | None = None,
) -> None:
    result = await conn.execute(
        text(
            """
            UPDATE golden_dataset
            SET status = 'golden', source = 'human_curated'
            WHERE id = :example_id AND org_id = :org_id AND brand_id = :brand_id
            RETURNING id
            """
        ),
        {"example_id": example_id, "org_id": org_id, "brand_id": brand_id},
    )
    if result.first() is None:
        raise ValueError("example not found in tenant scope")
    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="promoted_to_golden",
        actor_id=actor_id,
        entity_id=example_id,
        brand_id=brand_id,
        org_id=org_id,
    )


async def delete_example(
    conn: AsyncConnection,
    *,
    org_id: str,
    brand_id: str,
    example_id: str,
    actor_id: str | None = None,
) -> None:
    result = await conn.execute(
        text(
            """
            DELETE FROM golden_dataset
            WHERE id = :example_id AND org_id = :org_id AND brand_id = :brand_id
            RETURNING id
            """
        ),
        {"example_id": example_id, "org_id": org_id, "brand_id": brand_id},
    )
    if result.first() is None:
        raise ValueError("example not found in tenant scope")
    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="deleted",
        actor_id=actor_id,
        entity_id=example_id,
        brand_id=brand_id,
        org_id=org_id,
    )
