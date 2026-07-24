from __future__ import annotations

from sqlalchemy import text

from core.database import get_db
from pipeline.conversation_models import RecentCampaign


async def get_recent_campaigns(
    *,
    org_id: str,
    brand_ids: list[str],
    created_by: str | None = None,
    limit: int = 10,
) -> list[RecentCampaign]:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                WITH variant_counts AS (
                    SELECT campaign_id, COUNT(*) AS variant_count
                    FROM content_variants
                    GROUP BY campaign_id
                ),
                campaign_costs AS (
                    SELECT campaign_id, COALESCE(SUM(total_cost_usd), 0) AS token_cost_usd
                    FROM campaign_cost_attribution
                    GROUP BY campaign_id
                )
                SELECT
                    c.id,
                    c.brand_id,
                    c.status,
                    c.created_at,
                    COALESCE(cc.token_cost_usd, c.token_cost_usd, 0) AS token_cost_usd,
                    COALESCE(vc.variant_count, 0) AS variant_count
                FROM campaigns c
                LEFT JOIN variant_counts vc ON vc.campaign_id = c.id
                LEFT JOIN campaign_costs cc ON cc.campaign_id = c.id
                WHERE c.org_id = :org_id
                  AND (:brand_filter_disabled OR c.brand_id = ANY(CAST(:brand_ids AS UUID[])))
                                    AND (:created_by IS NULL OR c.created_by = CAST(:created_by AS UUID))
                ORDER BY c.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "org_id": org_id,
                "brand_filter_disabled": len(brand_ids) == 0,
                "brand_ids": brand_ids,
                "created_by": created_by,
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
        )
        for row in rows
    ]
