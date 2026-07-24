from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from core.config import settings
from core.database import get_db
from pipeline.graph import build_graph

ALLOWED_RESUME_NODES = {
    "intake_agent",
    "content_generator",
    "personalization_agent",
    "translation_agent",
    "judge_claude",
    "judge_gpt4o",
    "judge_llama",
    "confidence_aggregator",
    "review_gate",
    "publishing_agent",
    "publication_agent",
}


def _normalize_resume_node(node: str) -> str:
    if node == "publication_agent":
        return "publishing_agent"
    return node


def _to_psycopg_dsn(raw_dsn: str) -> str:
    dsn = raw_dsn.replace("+asyncpg", "")
    parts = urlsplit(dsn)
    if "@" not in parts.netloc:
        return dsn

    userinfo, hostpart = parts.netloc.rsplit("@", 1)
    if "%" not in userinfo:
        return dsn

    safe_userinfo = userinfo.replace("%", "%25")
    safe_netloc = f"{safe_userinfo}@{hostpart}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


class RerunService:
    async def rerun_campaign(
        self,
        *,
        campaign_id: str,
        resume_from_node: str,
        requested_by: str,
        trigger: str,
        user_edit: str | None,
        variant_task_id: str | None,
    ) -> dict[str, Any]:
        if resume_from_node not in ALLOWED_RESUME_NODES:
            raise ValueError(f"unsupported resume node: {resume_from_node}")

        normalized_resume_node = _normalize_resume_node(resume_from_node)

        psycopg_dsn = _to_psycopg_dsn(settings.POSTGRES_DSN)
        config = {"configurable": {"thread_id": campaign_id}}

        async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer)

            snapshot = await graph.aget_state(config)
            if snapshot is None:
                raise RuntimeError("campaign checkpoint not found")

            if variant_task_id:
                values = snapshot.values or {}
                current_task = next(
                    (t for t in (values.get("tasks") or []) if t.get("task_id") == variant_task_id),
                    None,
                )
                if current_task is None:
                    raise ValueError("variant_task_id not found in checkpoint tasks")
                await graph.aupdate_state(
                    config,
                    {"current_task": current_task},
                    as_node=normalized_resume_node,
                )

            if user_edit:
                await graph.aupdate_state(
                    config,
                    {"errors": [f"user_edit_note: {user_edit[:300]}"]},
                    as_node=normalized_resume_node,
                )

            final_state = await graph.ainvoke(None, config=config)

        revision_number = await self._next_revision_number(campaign_id)
        await self._insert_revision(
            campaign_id=campaign_id,
            revision_number=revision_number,
            trigger=trigger,
            resumed_from_node=normalized_resume_node,
            user_edit=user_edit,
            requested_by=requested_by,
        )

        return {
            "campaign_id": campaign_id,
            "revision_number": revision_number,
            # Backward-compat key used by frontend status text.
            "revision_id": revision_number,
            "resumed_from_node": normalized_resume_node,
            "status": (final_state or {}).get("current_phase", "running"),
        }

    async def _next_revision_number(self, campaign_id: str) -> int:
        async with get_db() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
                    FROM campaign_revisions
                    WHERE campaign_id = :campaign_id
                    """
                ),
                {"campaign_id": campaign_id},
            )
            row = result.mappings().one()
        return int(row["next_revision"])

    async def _insert_revision(
        self,
        *,
        campaign_id: str,
        revision_number: int,
        trigger: str,
        resumed_from_node: str,
        user_edit: str | None,
        requested_by: str,
    ) -> None:
        _ = requested_by
        async with get_db() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO campaign_revisions (
                        campaign_id,
                        revision_number,
                        trigger,
                        resumed_from_node,
                        user_edit,
                        cost_usd
                    )
                    VALUES (
                        :campaign_id,
                        :revision_number,
                        :trigger,
                        :resumed_from_node,
                        :user_edit,
                        0
                    )
                    """
                ),
                {
                    "campaign_id": campaign_id,
                    "revision_number": revision_number,
                    "trigger": trigger,
                    "resumed_from_node": resumed_from_node,
                    "user_edit": user_edit,
                },
            )
            await conn.commit()


rerun_service = RerunService()
