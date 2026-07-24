"""Review persistence, decision application, and resume orchestration.

Postgres is the source of truth. When a campaign pauses at the review gate the
worker calls :func:`persist_review_batch`. Reviewers act through the ``/reviews``
API (or the chat WebSocket) which calls :func:`apply_decision`; once every
review for a campaign is decided, :func:`resume_campaign` re-drives the
LangGraph run from its checkpoint.
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
from core.ids import new_uuid7
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pipeline.graph import build_graph
from sqlalchemy import text

from services import airtable_service
from services.audit_service import write_audit

log = structlog.get_logger()

_DECISION_TO_STATUS = {"approved": "approved", "rejected": "rejected", "edited": "edited"}
_DECISION_TO_AIRTABLE = {"approved": "Approved", "rejected": "Rejected", "edited": "Edited"}


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

    ``state["variants"]`` are keyed by ``task_id`` (a composite string such as
    ``"en-US_email_young_adults"``), not the DB UUID that ``content_variants``
    and ``review_requests`` reference. This function mints a fresh UUID per
    variant, persists it, and resolves every ``review_requests``/
    ``aggregated_scores`` row against that mapping before inserting.

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
    generated_at = datetime.now(UTC)

    task_to_variant_id: dict[str, str] = {}
    task_to_variant: dict[str, dict] = {v["task_id"]: v for v in variants}
    mirror_payloads: list[dict] = []

    async with get_db() as conn:
        requester_email = (
            await conn.execute(
                text(
                    """
                    SELECT u.email FROM campaigns c
                    LEFT JOIN users u ON u.id = c.created_by
                    WHERE c.id = CAST(:cid AS UUID)
                    """
                ),
                {"cid": campaign_id},
            )
        ).scalar_one_or_none()

        for variant in variants:
            variant_id = new_uuid7()
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
            # review_requests.id is a UUID column, but the in-memory
            # ReviewRequest.review_request_id is a short non-UUID string
            # (e.g. "rr_07d5b7d1583a415f") minted by the aggregator for
            # cheap in-graph correlation — mint a fresh UUID for the DB row,
            # independent of that in-memory id (mirrors the variant_id
            # task_id -> UUID mapping above).
            review_row_id = new_uuid7()
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
                    "id": review_row_id,
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
            variant = task_to_variant.get(review["variant_id"]) or {}
            mirror_payloads.append(
                {
                    "review_request_id": review_row_id,
                    "campaign_id": campaign_id,
                    "variant_id": variant_id,
                    "routing_reason": review.get("routing_reason"),
                    "Content": variant.get("final_content") or _variant_content(variant),
                    "Generated At": generated_at.isoformat(),
                    "Requester Email": requester_email,
                    "Decision": "Pending",
                    "Sync Status": "Not Synced",
                }
            )

        await conn.execute(
            text("UPDATE campaigns SET status = 'awaiting_review' WHERE id = CAST(:cid AS UUID)"),
            {"cid": campaign_id},
        )
        await conn.commit()

    for payload in mirror_payloads:
        await airtable_service.sync_review(payload)

    log.info(
        "review_batch_persisted",
        campaign_id=campaign_id,
        variants=len(variants),
        reviews=len(mirror_payloads),
    )
    return len(mirror_payloads)


async def resolve_reviewer_email(email: str) -> str | None:
    """Look up a user id by email. Used only by the Airtable webhook route
    (``api/routers/reviews.py::airtable_decide``) to attribute a decision made in
    Airtable to the individual reviewer who set it there — never called with a
    caller-supplied value on behalf of the human ``/decide`` route, since that
    would let any authenticated caller re-attribute a decision to someone else's
    identity in the audit log."""
    async with get_db() as conn:
        resolved = (
            await conn.execute(text("SELECT id FROM users WHERE email = :email"), {"email": email})
        ).scalar_one_or_none()
    return str(resolved) if resolved is not None else None


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

    ``actor_id`` is always the audit/``reviewed_by`` actor — callers that need to
    attribute the decision to someone other than their own authenticated identity
    (e.g. the Airtable webhook route, on behalf of a reviewer who acted in the
    grid) must resolve that identity themselves via :func:`resolve_reviewer_email`
    *before* calling this function, and only when authorized to do so.

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

    await airtable_service.sync_review(
        {
            "review_request_id": review_request_id,
            "Decision": _DECISION_TO_AIRTABLE[decision],
            "Reviewer Note": reviewer_note,
            "Sync Status": "Synced",
        }
    )

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
        # persist_review_batch mints fresh content_variants/aggregated_scores/
        # review_requests rows for this round and sets campaigns.status itself —
        # mirrors what the worker does for a campaign's first pause.
        await persist_review_batch(final_state or {})
        log.info("campaign_resumed", campaign_id=campaign_id, status="awaiting_review")
        return "awaiting_review"

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
