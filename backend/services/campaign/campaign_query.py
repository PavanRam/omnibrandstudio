from __future__ import annotations

from sqlalchemy import text

from core.database import get_db
from pipeline.conversation_models import RecentCampaign


async def get_recent_campaigns(
    *,
    org_id: str,
    brand_ids: list[str],
    created_by: str | None = None,
    include_archived: bool = False,
    limit: int = 10,
) -> list[RecentCampaign]:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    c.id,
                    c.brand_id,
                    c.status,
                    c.created_at,
                    -- Prefer attribution sum when token_cost_usd is 0 or NULL
                    -- (persist_draft_batch historically skipped the rollup;
                    --  the detail endpoint has the same fallback logic).
                    COALESCE(
                        NULLIF(c.token_cost_usd, 0),
                        attr.attribution_total,
                        0
                    ) AS token_cost_usd,
                    c.brief->>'objective' AS objective,
                    c.brief->>'target_audience' AS target_audience,
                    COUNT(v.task_id) AS variant_count
                FROM campaigns c
                LEFT JOIN (
                    SELECT campaign_id, SUM(total_cost_usd) AS attribution_total
                    FROM campaign_cost_attribution
                    GROUP BY campaign_id
                ) attr ON attr.campaign_id = c.id
                LEFT JOIN (
                    -- Edits INSERT a fresh row per re-run rather than
                    -- updating in place — count only the newest row per
                    -- task_id so an edited campaign's variant count doesn't
                    -- inflate with every regeneration.
                    SELECT DISTINCT ON (campaign_id, task_id) campaign_id, task_id
                    FROM content_variants
                    ORDER BY campaign_id, task_id, created_at DESC
                ) v ON v.campaign_id = c.id
                WHERE c.org_id = :org_id
                  AND (:brand_filter_disabled OR c.brand_id = ANY(CAST(:brand_ids AS UUID[])))
                                    AND (CAST(:created_by AS UUID) IS NULL OR c.created_by = CAST(:created_by AS UUID))
                  AND (:include_archived OR c.status != 'archived')
                GROUP BY c.id, c.brand_id, c.status, c.created_at, c.token_cost_usd,
                         attr.attribution_total, c.brief
                ORDER BY c.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "org_id": org_id,
                "brand_filter_disabled": len(brand_ids) == 0,
                "brand_ids": brand_ids,
                "created_by": created_by,
                "include_archived": include_archived,
                "limit": limit,
            },
        )
        rows = result.mappings().all()

    return [
        RecentCampaign(
            campaign_id=str(row["id"]),
            brand_id=str(row["brand_id"]),
            status=str(row["status"]),
            created_at=row["created_at"],
            variant_count=int(row["variant_count"] or 0),
            cost_usd=float(row["token_cost_usd"] or 0.0),
            objective=row["objective"],
            target_audience=row["target_audience"],
        )
        for row in rows
    ]
