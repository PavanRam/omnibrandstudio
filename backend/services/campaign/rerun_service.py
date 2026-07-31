from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from core.config import settings
from core.database import get_db
from pipeline.graph import build_graph
from services.review_service import persist_draft_batch

ALLOWED_RESUME_NODES = {
    "intake_agent",
    "content_generator",
    "personalization_agent",
    "translation_agent",
    "judge_1",
    "judge_2",
    "judge_3",
    "confidence_aggregator",
    "review_gate",
    "publishing_agent",
    "publication_agent",
}


def _normalize_resume_node(node: str) -> str:
    if node == "publication_agent":
        return "publishing_agent"
    return node


# LangGraph's aupdate_state(..., as_node=X) marks the checkpoint update as if
# node X just finished — the next resumed step is X's *successor*, not X
# itself. Passing the actual target node as as_node therefore silently SKIPS
# it on resume (confirmed empirically: content_generator never re-executed,
# so a "regenerate this variant" edit did nothing). The fix is to pass the
# target's own predecessor here instead, so the resume correctly lands on the
# target. Only covers the resume targets this API is actually exercised with
# today (the content edit flow); other ALLOWED_RESUME_NODES values fall back
# to the old (also-buggy) behavior rather than guessing at their — sometimes
# ambiguous/conditional — predecessor.
_RESUME_NODE_PREDECESSOR = {
    "content_generator": "intake_agent",
    "personalization_agent": "content_generator",
    "translation_agent": "personalization_agent",
}


def _as_node_for_resume(node: str) -> str:
    return _RESUME_NODE_PREDECESSOR.get(node, node)


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
        resume_as_node = _as_node_for_resume(normalized_resume_node)

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
                    as_node=resume_as_node,
                )

            if user_edit:
                # Plain field (not fan-in) — content_generator reads this and
                # folds it into the regeneration prompt, then clears it.
                # Previously this was appended to state["errors"], which
                # content_generator never read (feedback was silently
                # ignored) and which also broke the persist-after-rerun
                # success check below (every edit looked like a failed run).
                await graph.aupdate_state(
                    config,
                    {"user_edit_note": user_edit[:500]},
                    as_node=resume_as_node,
                )

            final_state = await graph.ainvoke(None, config=config)

        if isinstance(final_state, dict):
            current_phase = str(final_state.get("current_phase") or "").lower()
            if current_phase != "published":
                # Same "successful non-terminal run lands in draft" contract as
                # worker/main.py's needs_draft_persist — a manual rerun (whole
                # campaign or a single variant via variant_task_id) pauses
                # before review_gate again and must sync content_variants,
                # otherwise the regenerated content never leaves the LangGraph
                # checkpoint and the UI keeps showing stale content.
                #
                # Deliberately NOT gated on final_state["errors"] like the
                # worker's initial-run check is: this method itself appends a
                # "user_edit_note: ..." entry to that same fan-in field below
                # whenever user_edit is provided, which would make every
                # feedback-driven edit look like a failed run.
                await persist_draft_batch(final_state)

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
