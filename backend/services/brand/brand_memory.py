from __future__ import annotations

import json

from sqlalchemy import text

from core.database import get_db


class BrandMemoryService:
    async def get(self, brand_id: str) -> dict:
        async with get_db() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        id,
                        brand_id,
                        org_id,
                        preferred_channels,
                        tone_by_channel,
                        top_ctas,
                        recent_campaign_summary,
                        updated_at
                    FROM brand_memories
                    WHERE brand_id = :brand_id
                    """
                ),
                {"brand_id": brand_id},
            )
            row = result.mappings().first()

        if row is None:
            return {}

        return {
            "id": str(row["id"]),
            "brand_id": str(row["brand_id"]),
            "org_id": str(row["org_id"]),
            "preferred_channels": row["preferred_channels"] or [],
            "tone_by_channel": row["tone_by_channel"] or {},
            "top_ctas": row["top_ctas"] or [],
            "recent_campaign_summary": row["recent_campaign_summary"],
            "updated_at": row["updated_at"],
        }

    async def upsert(
        self,
        *,
        brand_id: str,
        org_id: str,
        preferred_channels: list[str] | None = None,
        tone_by_channel: dict | None = None,
        top_ctas: list[str] | None = None,
        recent_campaign_summary: str | None = None,
    ) -> None:
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO brand_memories (
                        brand_id,
                        org_id,
                        preferred_channels,
                        tone_by_channel,
                        top_ctas,
                        recent_campaign_summary,
                        updated_at
                    )
                    VALUES (
                        :brand_id,
                        :org_id,
                        CAST(:preferred_channels AS JSONB),
                        CAST(:tone_by_channel AS JSONB),
                        CAST(:top_ctas AS JSONB),
                        :recent_campaign_summary,
                        NOW()
                    )
                    ON CONFLICT (brand_id)
                    DO UPDATE SET
                        preferred_channels = CAST(:preferred_channels AS JSONB),
                        tone_by_channel = CAST(:tone_by_channel AS JSONB),
                        top_ctas = CAST(:top_ctas AS JSONB),
                        recent_campaign_summary = :recent_campaign_summary,
                        updated_at = NOW()
                    """
                ),
                {
                    "brand_id": brand_id,
                    "org_id": org_id,
                    "preferred_channels": json.dumps(preferred_channels or []),
                    "tone_by_channel": json.dumps(tone_by_channel or {}),
                    "top_ctas": json.dumps(top_ctas or []),
                    "recent_campaign_summary": recent_campaign_summary,
                },
            )
            await conn.commit()


brand_memory_service = BrandMemoryService()
