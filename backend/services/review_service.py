"""T11 — review persistence, decision application, and resume orchestration.

Postgres is the source of truth. When a campaign pauses at the review gate the
worker calls :func:`persist_review_batch`. Reviewers act through the ``/reviews``
API which calls :func:`apply_decision`; once every review for a campaign is
decided, :func:`resume_campaign` re-drives the LangGraph run from its checkpoint.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog
from core.config import settings
from core.database import get_db
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pipeline.graph import build_graph
from sqlalchemy import text

from services import airtable_service
from services.audit_service import write_audit

log = structlog.get_logger()

_DECISION_TO_STATUS = {"approved": "approved", "rejected": "rejected", "edited": "edited"}


def _to_psycopg_dsn(raw_dsn: str) -> str:
    """psycopg-compatible DSN (strip +asyncpg, escape bare % in userinfo)."""
    dsn = raw_dsn.replace("+asyncpg", "")
    parts = urlsplit(dsn)
    if "@" not in parts.netloc:
        return dsn
    userinfo, hostpart = parts.netloc.rsplit("@", 1)
    if "%" not in userinfo:
        return dsn
    safe_netloc = f"{userinfo.replace('%', '%25')}@{hostpart}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


def _variant_content(variant: dict) -> str | None:
    return (
        variant.get("translated_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
    )


def _as_uuid_or_none(value: object) -> str | None:
    """Coerce an actor id to a UUID string, or None. API-key auth uses the
    non-UUID sentinel ``"api_key"`` as the user id; ``reviewed_by`` and the audit
    ``actor_id`` are UUID columns, so a non-UUID actor is stored as NULL."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


async def persist_review_batch(state: dict) -> int:
    """Persist variants + aggregated scores + review requests for a paused,
    review-flagged campaign, then set ``campaigns.status='awaiting_review'``.

    Returns the number of review requests persisted. Postgres is the source of
    truth (failure propagates); the Airtable mirror is best-effort afterwards.
    """
    campaign_id = state["campaign_id"]
    org_id = state["org_id"]
    brand_id = state["brand_id"]
    variants = state.get("variants", [])
    aggregated = {a["variant_id"]: a for a in state.get("aggregated_scores", [])}
    reviews = state.get("review_requests", [])
    sla_deadline = datetime.now(UTC) + timedelta(hours=settings.REVIEW_SLA_HOURS)
    reviewer = ((state.get("org_config") or {}).get("review") or {}).get("default_assignee")

    task_to_variant_id: dict[str, str] = {}
    mirror_payloads: list[dict] = []

    async with get_db() as conn:
        for variant in variants:
            variant_id = str(uuid.uuid4())
            task_to_variant_id[variant["task_id"]] = variant_id
            await conn.execute(
                text(
                    """
                    INSERT INTO content_variants
                        (id, campaign_id, task_id, locale, channel, segment,
                         generated_content, personalized_content, translated_content,
                         final_content, status, generation_model, prompt_version,
                         retry_count, reflexion_applied)
                    VALUES
                        (:id, :campaign_id, :task_id, :locale, :channel, :segment,
                         :generated_content, :personalized_content, :translated_content,
                         :final_content, :status, :generation_model, :prompt_version,
                         :retry_count, :reflexion_applied)
                    """
                ),
                {
                    "id": variant_id,
                    "campaign_id": campaign_id,
                    "task_id": variant["task_id"],
                    "locale": variant.get("locale", ""),
                    "channel": variant.get("channel", ""),
                    "segment": variant.get("segment", ""),
                    "generated_content": variant.get("generated_content"),
                    "personalized_content": variant.get("personalized_content"),
                    "translated_content": variant.get("translated_content"),
                    "final_content": variant.get("final_content") or _variant_content(variant),
                    "status": variant.get("status", "pending"),
                    "generation_model": variant.get("generation_model"),
                    "prompt_version": variant.get("prompt_version"),
                    "retry_count": int(variant.get("retry_count", 0) or 0),
                    "reflexion_applied": bool(variant.get("reflexion_applied", False)),
                },
            )

            agg = aggregated.get(variant["task_id"])
            if agg:
                await conn.execute(
                    text(
                        """
                        INSERT INTO aggregated_scores
                            (variant_id, judge_scores, weighted_mean, variance,
                             consensus_level, any_critical_violation, critical_violations,
                             routing_decision, routing_reason, degraded_mode)
                        VALUES
                            (:variant_id, CAST(:judge_scores AS JSONB), :weighted_mean, :variance,
                             :consensus_level, :any_critical_violation, :critical_violations,
                             :routing_decision, :routing_reason, :degraded_mode)
                        """
                    ),
                    {
                        "variant_id": variant_id,
                        "judge_scores": json.dumps(agg.get("judge_scores", [])),
                        "weighted_mean": agg.get("weighted_mean", 0.0),
                        "variance": agg.get("variance", 0.0),
                        "consensus_level": agg.get("consensus_level", "unknown"),
                        "any_critical_violation": bool(agg.get("any_critical_violation", False)),
                        "critical_violations": agg.get("critical_violations", []),
                        "routing_decision": agg.get("routing_decision", "flag"),
                        "routing_reason": agg.get("routing_reason"),
                        "degraded_mode": bool(agg.get("degraded_mode", False)),
                    },
                )

        for review in reviews:
            variant_id = task_to_variant_id.get(review["variant_id"])
            if variant_id is None:
                continue
            await conn.execute(
                text(
                    """
                    INSERT INTO review_requests
                        (id, variant_id, campaign_id, org_id, brand_id, routing_reason,
                         scores_snapshot, status, sla_deadline, reviewed_by)
                    VALUES
                        (:id, :variant_id, :campaign_id, :org_id, :brand_id, :routing_reason,
                         CAST(:scores_snapshot AS JSONB), 'pending', :sla_deadline, :reviewed_by)
                    """
                ),
                {
                    "id": review["review_request_id"],
                    "variant_id": variant_id,
                    "campaign_id": campaign_id,
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "routing_reason": review.get("routing_reason"),
                    "scores_snapshot": json.dumps(review.get("scores_snapshot", [])),
                    "sla_deadline": sla_deadline,
                    "reviewed_by": reviewer,
                },
            )
            mirror_payloads.append(
                {
                    "review_request_id": review["review_request_id"],
                    "campaign_id": campaign_id,
                    "variant_id": variant_id,
                    "status": "pending",
                    "routing_reason": review.get("routing_reason"),
                }
            )

        await conn.execute(
            text("UPDATE campaigns SET status = 'awaiting_review' WHERE id = CAST(:cid AS UUID)"),
            {"cid": campaign_id},
        )
        await conn.commit()

    for payload in mirror_payloads:
        await airtable_service.upsert_review(payload)

    log.info(
        "review_batch_persisted",
        campaign_id=campaign_id,
        variants=len(variants),
        reviews=len(mirror_payloads),
    )
    return len(mirror_payloads)


async def apply_decision(
    review_request_id: str,
    decision: str,
    reviewer_note: str | None,
    edited_content: str | None,
    *,
    actor_id: str,
    brand_ids: list[str],
) -> dict[str, Any]:
    """Apply a reviewer decision to Postgres (review row + variant), audit it, and
    report whether the campaign's reviews are now all decided.

    Raises ``LookupError`` (404), ``PermissionError`` (403), or ``ValueError`` (409)
    for the router to translate into HTTP status codes.
    """
    final_status = _DECISION_TO_STATUS[decision]
    actor_uuid = _as_uuid_or_none(actor_id)

    async with get_db() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT rr.id, rr.status, rr.campaign_id, rr.brand_id, rr.org_id,
                           rr.variant_id, cv.task_id
                    FROM review_requests rr
                    JOIN content_variants cv ON cv.id = rr.variant_id
                    WHERE rr.id = CAST(:id AS UUID)
                    """
                ),
                {"id": review_request_id},
            )
        ).mappings().first()

        if row is None:
            raise LookupError("review request not found")
        if brand_ids and str(row["brand_id"]) not in brand_ids:
            raise PermissionError("review request outside brand scope")
        if str(row["status"]) != "pending":
            raise ValueError(f"review already decided (status={row['status']})")

        await conn.execute(
            text(
                """
                UPDATE review_requests
                SET status = :status, decision = :decision, reviewer_note = :note,
                    edited_content = :edited, reviewed_by = :actor, reviewed_at = NOW()
                WHERE id = CAST(:id AS UUID)
                """
            ),
            {
                "status": final_status,
                "decision": decision,
                "note": reviewer_note,
                "edited": edited_content,
                "actor": actor_uuid,
                "id": review_request_id,
            },
        )

        # Reflect on the variant. For edits, the reviewer content becomes final.
        await conn.execute(
            text(
                """
                UPDATE content_variants
                SET status = :status,
                    final_content = CASE WHEN CAST(:edited AS TEXT) IS NOT NULL
                                         THEN CAST(:edited AS TEXT) ELSE final_content END
                WHERE id = :variant_id
                """
            ),
            {"status": final_status, "edited": edited_content, "variant_id": row["variant_id"]},
        )

        await write_audit(
            conn,
            entity_type="review_request",
            action="decide",
            actor_id=actor_uuid,
            entity_id=review_request_id,
            brand_id=str(row["brand_id"]),
            org_id=str(row["org_id"]),
            after_val={
                "decision": decision,
                "status": final_status,
                "reviewer_note": reviewer_note,
            },
        )

        remaining = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS n FROM review_requests
                    WHERE campaign_id = :cid AND status = 'pending'
                    """
                ),
                {"cid": row["campaign_id"]},
            )
        ).scalar_one()
        await conn.commit()

    await airtable_service.patch_decision(review_request_id, decision, final_status)

    return {
        "campaign_id": str(row["campaign_id"]),
        "task_id": str(row["task_id"]),
        "all_decided": int(remaining) == 0,
    }


async def resume_campaign(campaign_id: str) -> str:
    """Resume a paused campaign: inject the collected decisions into the checkpoint
    and re-drive the graph. Returns the resulting campaign status."""
    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT rr.decision, rr.reviewer_note, rr.edited_content, cv.task_id
                    FROM review_requests rr
                    JOIN content_variants cv ON cv.id = rr.variant_id
                    WHERE rr.campaign_id = :cid
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().all()

    decisions = {
        str(r["task_id"]): {
            "decision": r["decision"],
            "reviewer_note": r["reviewer_note"],
            "edited_content": r["edited_content"],
        }
        for r in rows
        if r["decision"]
    }

    psycopg_dsn = _to_psycopg_dsn(settings.POSTGRES_DSN)
    config = {"configurable": {"thread_id": campaign_id}}
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        await graph.aupdate_state(config, {"review_decisions": decisions})
        final_state = await graph.ainvoke(None, config)

    phase = str((final_state or {}).get("current_phase") or "").lower()
    if phase == "published":
        status, mark_completed = "published", True
    elif (final_state or {}).get("errors"):
        status, mark_completed = "failed", True
    else:
        # Another review round was created (reject → regenerate → paused again).
        status, mark_completed = "awaiting_review", False

    async with get_db() as conn:
        await conn.execute(
            text(
                """
                UPDATE campaigns
                SET status = :status,
                    completed_at = CASE WHEN :done THEN NOW() ELSE completed_at END
                WHERE id = CAST(:cid AS UUID)
                """
            ),
            {"status": status, "done": mark_completed, "cid": campaign_id},
        )
        await conn.commit()

    log.info("campaign_resumed", campaign_id=campaign_id, status=status)
    return status
