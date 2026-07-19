from __future__ import annotations

import json

from sqlalchemy import text

from core.database import get_db
from core.redis import get_redis
from pipeline.conversation_models import ConversationSession, PartialBrief, RecentConversation

_CACHE_KEY_PREFIX = "conversation:session"
_CACHE_TTL_SECONDS = 600


class SessionManager:
    def _cache_key(self, conversation_id: str) -> str:
        return f"{_CACHE_KEY_PREFIX}:{conversation_id}"

    async def get(self, conversation_id: str) -> ConversationSession | None:
        try:
            cached = await get_redis().get(self._cache_key(conversation_id))
            if cached:
                return ConversationSession.model_validate_json(cached)
        except Exception:
            pass

        async with get_db() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                        id,
                        brand_id,
                        org_id,
                        created_by,
                        status,
                        partial_brief,
                        active_campaign_id,
                        campaign_ids,
                        summary,
                        created_at,
                        updated_at
                    FROM conversations
                    WHERE id = :conversation_id
                    """
                ),
                {"conversation_id": conversation_id},
            )
            row = result.mappings().first()

        if row is None:
            return None

        session = ConversationSession(
            id=str(row["id"]),
            brand_id=str(row["brand_id"]),
            org_id=str(row["org_id"]),
            created_by=str(row["created_by"]) if row["created_by"] else None,
            status=str(row["status"]),
            partial_brief=PartialBrief.model_validate(row["partial_brief"] or {}),
            active_campaign_id=str(row["active_campaign_id"]) if row["active_campaign_id"] else None,
            campaign_ids=[str(c) for c in (row["campaign_ids"] or [])],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        await self._cache_set(session)
        return session

    async def create(self, org_id: str, brand_id: str, created_by: str | None) -> ConversationSession:
        async with get_db() as conn:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO conversations (org_id, brand_id, created_by)
                    VALUES (:org_id, :brand_id, :created_by)
                    RETURNING
                        id,
                        brand_id,
                        org_id,
                        created_by,
                        status,
                        partial_brief,
                        active_campaign_id,
                        campaign_ids,
                        summary,
                        created_at,
                        updated_at
                    """
                ),
                {
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "created_by": created_by,
                },
            )
            row = result.mappings().one()
            await conn.commit()

        session = ConversationSession(
            id=str(row["id"]),
            brand_id=str(row["brand_id"]),
            org_id=str(row["org_id"]),
            created_by=str(row["created_by"]) if row["created_by"] else None,
            status=str(row["status"]),
            partial_brief=PartialBrief.model_validate(row["partial_brief"] or {}),
            active_campaign_id=str(row["active_campaign_id"]) if row["active_campaign_id"] else None,
            campaign_ids=[str(c) for c in (row["campaign_ids"] or [])],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        await self._cache_set(session)
        return session

    async def list_recent(
        self,
        *,
        org_id: str,
        brand_ids: list[str] | None,
        created_by: str | None = None,
        limit: int = 12,
    ) -> list[RecentConversation]:
        async with get_db() as conn:
            if created_by:
                result = await conn.execute(
                    text(
                        """
                        SELECT
                            id,
                            brand_id,
                            status,
                            active_campaign_id,
                            partial_brief,
                            updated_at
                        FROM conversations
                        WHERE org_id = :org_id
                          AND created_by = CAST(:created_by AS UUID)
                        ORDER BY updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"org_id": org_id, "created_by": created_by, "limit": limit},
                )
            else:
                result = await conn.execute(
                    text(
                        """
                        SELECT
                            id,
                            brand_id,
                            status,
                            active_campaign_id,
                            partial_brief,
                            updated_at
                        FROM conversations
                        WHERE org_id = :org_id
                        ORDER BY updated_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"org_id": org_id, "limit": limit},
                )
            rows = result.mappings().all()

        allowed = set(brand_ids or [])
        filtered = [
            row
            for row in rows
            if not allowed or str(row["brand_id"]) in allowed
        ]
        return [
            RecentConversation(
                conversation_id=str(row["id"]),
                brand_id=str(row["brand_id"]),
                status=str(row["status"]),
                active_campaign_id=str(row["active_campaign_id"]) if row["active_campaign_id"] else None,
                partial_brief=PartialBrief.model_validate(row["partial_brief"] or {}),
                updated_at=row["updated_at"],
            )
            for row in filtered
        ]

    async def update_partial_brief(self, conversation_id: str, partial_brief: PartialBrief) -> None:
        brief_json = partial_brief.model_dump_json()
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE conversations
                    SET partial_brief = CAST(:partial_brief AS JSONB), updated_at = NOW()
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "partial_brief": brief_json,
                },
            )
            await conn.commit()

        session = await self.get(conversation_id)
        if session is not None:
            session.partial_brief = partial_brief
            await self._cache_set(session)

    async def attach_campaign(self, conversation_id: str, campaign_id: str) -> None:
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE conversations
                    SET
                        active_campaign_id = :campaign_id,
                        campaign_ids = array_append(campaign_ids, CAST(:campaign_id AS UUID)),
                        status = 'processing',
                        updated_at = NOW()
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "campaign_id": campaign_id,
                },
            )
            await conn.commit()

        session = await self.get(conversation_id)
        if session is not None:
            session.active_campaign_id = campaign_id
            if campaign_id not in session.campaign_ids:
                session.campaign_ids.append(campaign_id)
            session.status = "processing"
            await self._cache_set(session)

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intent_classified: str | None = None,
        campaign_id: str | None = None,
    ) -> None:
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO conversation_messages (
                        conversation_id,
                        role,
                        content,
                        intent_classified,
                        campaign_id
                    )
                    VALUES (:conversation_id, :role, :content, :intent_classified, :campaign_id)
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "role": role,
                    "content": content,
                    "intent_classified": intent_classified,
                    "campaign_id": campaign_id,
                },
            )
            await conn.commit()

    async def load_messages(self, conversation_id: str, limit: int = 30) -> list[dict[str, str]]:
        async with get_db() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT role, content
                    FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"conversation_id": conversation_id, "limit": limit},
            )
            rows = result.mappings().all()

        ordered = list(reversed(rows))
        return [{"role": str(row["role"]), "content": str(row["content"])} for row in ordered]

    async def _cache_set(self, session: ConversationSession) -> None:
        try:
            await get_redis().setex(
                self._cache_key(session.id),
                _CACHE_TTL_SECONDS,
                session.model_dump_json(),
            )
        except Exception:
            pass


session_manager = SessionManager()
