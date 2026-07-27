"""Review persistence, decision application, and resume orchestration.

Postgres is the source of truth. When a campaign pauses at the review gate the
worker calls :func:`persist_draft_batch`, which stores content but leaves the
campaign in ``draft`` — nothing is sent to reviewers yet. The campaign's
creator previews the draft and explicitly calls :func:`send_campaign_to_review`
(via ``POST /campaigns/{id}/send-to-review``), which creates the actual
``review_requests`` rows and flips the campaign to ``awaiting_review``.
Reviewers act through the ``/reviews`` API (or the chat WebSocket) which calls
:func:`apply_decision`; once every review for a campaign is decided,
:func:`resume_campaign` re-drives the LangGraph run from its checkpoint.
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

from services import airtable_service, notification_service
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


async def persist_draft_batch(state: dict) -> int:
    """Persist variants + aggregated scores for a completed pipeline run, then
    set ``campaigns.status='draft'`` so the campaign's creator can preview the
    generated content before anyone sends it to human review.

    ``state["variants"]`` are keyed by ``task_id`` (a composite string such as
    ``"en-US_email_young_adults"``), not the DB UUID that ``content_variants``
    references. This function mints a fresh UUID per variant and resolves
    every ``aggregated_scores`` row against that mapping before inserting.

    Deliberately does *not* create ``review_requests`` rows or touch Airtable —
    that happens later, on demand, via :func:`send_campaign_to_review`, once
    the creator has actually looked at the content.

    Returns the number of variants persisted.
    """
    campaign_id = state["campaign_id"]
    variants = state.get("variants", [])
    aggregated = {a["variant_id"]: a for a in state.get("aggregated_scores", [])}
    # brand_scores table exists (001_core_schema.py) but was never actually
    # inserted into anywhere until now — the per-judge model/score/reasoning
    # breakdown only ever lived in-memory during the run. Needed for the
    # "Run summary" panel's Judge gate section (2026-07-27).
    brand_scores_by_task: dict[str, list[dict]] = {}
    for bs in state.get("brand_scores", []):
        brand_scores_by_task.setdefault(bs["variant_id"], []).append(bs)

    async with get_db() as conn:
        for variant in variants:
            variant_id = new_uuid7()
            await conn.execute(
                text(
                    """
                    INSERT INTO content_variants
                        (id, campaign_id, task_id, locale, channel, segment,
                         generated_content, personalized_content, translated_content,
                         final_content, status, generation_model, prompt_version,
                         translation_engine, back_translation_score, failure_reason,
                         translation_checks, retry_count, reflexion_applied)
                    VALUES
                        (:id, :campaign_id, :task_id, :locale, :channel, :segment,
                         :generated_content, :personalized_content, :translated_content,
                         :final_content, :status, :generation_model, :prompt_version,
                         :translation_engine, :back_translation_score, :failure_reason,
                         CAST(:translation_checks AS JSONB), :retry_count, :reflexion_applied)
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
                    "translation_engine": variant.get("translation_engine"),
                    "back_translation_score": variant.get("back_translation_score"),
                    "failure_reason": variant.get("failure_reason"),
                    "translation_checks": json.dumps(variant.get("translation_checks"))
                    if variant.get("translation_checks") is not None
                    else None,
                    "retry_count": int(variant.get("retry_count", 0) or 0),
                    "reflexion_applied": bool(variant.get("reflexion_applied", False)),
                },
            )

            for bs in brand_scores_by_task.get(variant["task_id"], []):
                await conn.execute(
                    text(
                        """
                        INSERT INTO brand_scores
                            (variant_id, judge_model, composite_score, scores,
                             critical_violations, routing_decision, evaluation_latency_ms,
                             evaluation_round)
                        VALUES
                            (:variant_id, :judge_model, :composite_score, CAST(:scores AS JSONB),
                             :critical_violations, :routing_decision, :evaluation_latency_ms,
                             :evaluation_round)
                        """
                    ),
                    {
                        "variant_id": variant_id,
                        "judge_model": bs.get("judge_model", "unknown"),
                        "composite_score": bs.get("composite_score", 0.0),
                        "scores": json.dumps(bs.get("scores", {})),
                        "critical_violations": bs.get("critical_violations", []),
                        "routing_decision": bs.get("routing_decision", "flag"),
                        "evaluation_latency_ms": bs.get("evaluation_latency_ms"),
                        "evaluation_round": int(bs.get("evaluation_round", 0) or 0),
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

        await conn.execute(
            text("UPDATE campaigns SET status = 'draft' WHERE id = CAST(:cid AS UUID)"),
            {"cid": campaign_id},
        )
        await conn.commit()

    log.info("draft_batch_persisted", campaign_id=campaign_id, variants=len(variants))
    return len(variants)


async def send_campaign_to_review(campaign_id: str) -> int:
    """Move a ``draft`` campaign to ``awaiting_review``: create a
    ``review_requests`` row for EVERY variant that doesn't already have one,
    regardless of the judge panel's ``routing_decision``, then hand off to
    human reviewers.

    No-auto-publish policy (2026-07-27, user request): every campaign — even
    one where every variant was judge ``auto_approve`` — requires an explicit
    human decision before it can publish. Previously ``auto_approve``
    variants were excluded here entirely, which meant they never appeared in
    Airtable or the in-app review dialog and could publish with zero human
    involvement (found live: campaign 019fa4b8 auto-published without ever
    being reviewed). Judge/reflexion routing_decision still controls
    automated quality gating upstream of this function — this only removes
    the "skip the human" shortcut at publish time.

    Reconstructs everything it needs from already-persisted
    ``content_variants``/``aggregated_scores`` rows (written by
    :func:`persist_draft_batch`) rather than from in-memory pipeline state,
    since this runs later, triggered by the campaign's creator clicking
    "send for review" — not by the worker inline.

    Returns the number of review requests created. Idempotent: calling it
    again after some/all reviews are already created only fills the gaps.
    """
    sla_deadline = datetime.now(UTC) + timedelta(hours=settings.REVIEW_SLA_HOURS)
    generated_at = datetime.now(UTC)
    mirror_payloads: list[dict] = []

    async with get_db() as conn:
        campaign_row = (
            await conn.execute(
                text(
                    """
                    SELECT c.org_id, c.brand_id, c.brief->>'objective' AS objective,
                           u.email AS requester_email
                    FROM campaigns c
                    LEFT JOIN users u ON u.id = c.created_by
                    WHERE c.id = CAST(:cid AS UUID)
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().first()
        if campaign_row is None:
            raise LookupError("campaign not found")
        org_id = str(campaign_row["org_id"])
        brand_id = str(campaign_row["brand_id"])
        requester_email = campaign_row["requester_email"]
        objective = campaign_row["objective"] or "Your campaign"

        needs_review = (
            await conn.execute(
                text(
                    """
                    WITH latest_variants AS (
                        -- Edits INSERT a fresh row per re-run rather than
                        -- updating in place — only the newest row per
                        -- task_id is the one actually awaiting review.
                        SELECT DISTINCT ON (task_id) *
                        FROM content_variants
                        WHERE campaign_id = CAST(:cid AS UUID)
                        ORDER BY task_id, created_at DESC
                    )
                    SELECT cv.id AS variant_id, cv.generated_content, cv.personalized_content,
                           cv.translated_content, a.routing_reason, a.judge_scores
                    FROM latest_variants cv
                    JOIN aggregated_scores a ON a.variant_id = cv.id
                    LEFT JOIN review_requests rr ON rr.variant_id = cv.id
                    WHERE rr.id IS NULL
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().all()

        for row in needs_review:
            review_row_id = new_uuid7()
            await conn.execute(
                text(
                    """
                    INSERT INTO review_requests
                        (id, variant_id, campaign_id, org_id, brand_id, routing_reason,
                         scores_snapshot, status, sla_deadline, reviewed_by)
                    VALUES
                        (:id, :variant_id, :campaign_id, :org_id, :brand_id, :routing_reason,
                         CAST(:scores_snapshot AS JSONB), 'pending', :sla_deadline, NULL)
                    """
                ),
                {
                    "id": review_row_id,
                    "variant_id": str(row["variant_id"]),
                    "campaign_id": campaign_id,
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "routing_reason": row["routing_reason"],
                    "scores_snapshot": json.dumps(row["judge_scores"] or []),
                    "sla_deadline": sla_deadline,
                },
            )
            mirror_payloads.append(
                {
                    "review_request_id": review_row_id,
                    "campaign_id": campaign_id,
                    "variant_id": str(row["variant_id"]),
                    "routing_reason": row["routing_reason"],
                    "Generated Content": row["generated_content"],
                    "Personalized Content": row["personalized_content"],
                    "Translated Content": row["translated_content"],
                    "Generated At": generated_at.isoformat(),
                    "Requester Email": requester_email,
                    "Decision": "Pending",
                    "Sync Status": "Not Synced",
                }
            )

        # 2026-07-27, found live (campaign 019fa4b8): a campaign where every
        # variant is judge-auto-approved creates zero review_requests here
        # (by design — nothing needs a human decision) but was still
        # unconditionally flipped to 'awaiting_review'. Nothing ever calls
        # resume_campaign for it after that — apply_decision only fires from
        # an actual reviewer decision, and there are none to make — so the
        # campaign was stuck forever with an empty review list, no path to
        # publish. Skip 'awaiting_review' entirely in that case and resume
        # immediately below instead.
        total_pending = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM review_requests WHERE campaign_id = CAST(:cid AS UUID) AND status = 'pending'"
                ),
                {"cid": campaign_id},
            )
        ).scalar_one()

        if total_pending > 0:
            await conn.execute(
                text("UPDATE campaigns SET status = 'awaiting_review' WHERE id = CAST(:cid AS UUID)"),
                {"cid": campaign_id},
            )
        await conn.commit()

    for payload in mirror_payloads:
        await airtable_service.sync_review(payload)

    if mirror_payloads:
        await notification_service.notify_review_task(
            org_id=org_id, brand_id=brand_id, campaign_id=campaign_id, title=objective
        )

    log.info("campaign_sent_to_review", campaign_id=campaign_id, reviews=len(mirror_payloads))

    if total_pending == 0:
        await resume_campaign(campaign_id)

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
                           rr.variant_id, cv.task_id, c.created_by, c.brief->>'objective' AS objective
                    FROM review_requests rr
                    JOIN content_variants cv ON cv.id = rr.variant_id
                    JOIN campaigns c ON c.id = rr.campaign_id
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

    await notification_service.notify_decision(
        org_id=str(row["org_id"]),
        brand_id=str(row["brand_id"]),
        campaign_id=str(row["campaign_id"]),
        created_by=str(row["created_by"]) if row["created_by"] else None,
        title=row["objective"] or "Your campaign",
        decision=decision,
    )

    return {
        "campaign_id": str(row["campaign_id"]),
        "task_id": str(row["task_id"]),
        "all_decided": int(remaining) == 0,
    }


def _format_rejection_message(rejected_rows: list[Any]) -> str:
    count = len(rejected_rows)
    plural = "variant" if count == 1 else "variants"
    lines = [f"**{count} {plural} rejected — changes requested:**", ""]
    for i, r in enumerate(rejected_rows, start=1):
        note = (r["reviewer_note"] or "no comment left").strip()
        lines.append(f'{i}. **{r["channel"]} · {r["locale"]}** — "{note}"')
    lines.append("")
    lines.append("Let me know what changes you'd like, and I'll regenerate the affected content.")
    return "\n".join(lines)


async def _park_for_revision(campaign_id: str, rejected_rows: list[Any]) -> str:
    """A rejection stops the pipeline instead of auto-regenerating. Notifies the
    creator and drops a message with every rejected variant + its reviewer
    comment into the originating conversation, then waits for the creator's
    reply (handled by conversations.py's needs_revision branch)."""
    from services.chat.session_manager import session_manager

    async with get_db() as conn:
        campaign_row = (
            await conn.execute(
                text(
                    """
                    SELECT org_id, brand_id, created_by, brief->>'objective' AS objective
                    FROM campaigns WHERE id = CAST(:cid AS UUID)
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().first()

        await conn.execute(
            text("UPDATE campaigns SET status = 'needs_revision' WHERE id = CAST(:cid AS UUID)"),
            {"cid": campaign_id},
        )
        await conn.commit()

        conversation_row = (
            await conn.execute(
                text(
                    """
                    SELECT id FROM conversations
                    WHERE CAST(:cid AS UUID) = ANY(campaign_ids)
                       OR active_campaign_id = CAST(:cid AS UUID)
                    LIMIT 1
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().first()

    message = _format_rejection_message(rejected_rows)
    if conversation_row is not None:
        conversation_id = str(conversation_row["id"])
        await session_manager.set_status(conversation_id, "reviewing")
        await session_manager.add_message(
            conversation_id,
            "assistant",
            message,
            intent_classified="revision_requested",
            campaign_id=campaign_id,
        )

    if campaign_row is not None:
        await notification_service.notify_variants_rejected(
            org_id=str(campaign_row["org_id"]),
            brand_id=str(campaign_row["brand_id"]),
            campaign_id=campaign_id,
            created_by=str(campaign_row["created_by"]) if campaign_row["created_by"] else None,
            title=campaign_row["objective"] or "Your campaign",
            rejected_items=[dict(r) for r in rejected_rows],
        )

    log.info(
        "campaign_parked_for_revision",
        campaign_id=campaign_id,
        rejected_count=len(rejected_rows),
        conversation_id=str(conversation_row["id"]) if conversation_row is not None else None,
    )
    return "needs_revision"


async def resume_campaign(campaign_id: str) -> str:
    """Resume a paused campaign: inject the collected decisions into the checkpoint
    and re-drive the graph. Returns the resulting campaign status.

    A rejection is handled entirely differently from approve/edit: it does NOT
    resume the graph at all. Resuming used to route to content_generator with
    state["current_task"] unset, which falls into the full task loop and
    silently regenerates every variant (including already-approved ones) —
    see next_tasks.md item 6 (2026-07-27). Instead, a rejection now hands
    control back to the campaign's creator: the campaign is parked in
    'needs_revision', the creator is notified, and an assistant message
    listing every rejected variant + its reviewer comment is injected into
    the originating conversation. The creator's next reply in that
    conversation drives a scoped, single-variant regeneration via
    rerun_service (see api/routers/conversations.py's needs_revision branch)
    — never an automatic, unscoped one.
    """
    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT rr.decision, rr.reviewer_note, rr.edited_content,
                           cv.task_id, cv.channel, cv.locale, cv.segment
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

    rejected_rows = [r for r in rows if r["decision"] == "rejected"]
    if rejected_rows:
        return await _park_for_revision(campaign_id, rejected_rows)

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
        # Defensive fallback only — with every 'rejected' decision now
        # short-circuited above via _park_for_revision, this batch was
        # approved/edited-only, so the graph should already have reached
        # 'published' or failed. If it instead paused again for some other
        # reason, still route the fresh draft back to review rather than
        # leaving it stuck with no outward status change.
        await persist_draft_batch(final_state or {})
        await send_campaign_to_review(campaign_id)
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

        if status == "published":
            # Same "fetch org/brand/created_by/objective, then notify" pattern
            # worker/main.py already uses for draft_ready/campaign_failed —
            # resume_campaign is the single choke point for this transition
            # regardless of which decision source (in-app dialog or Airtable
            # poller) triggered the resume, so one call here covers both.
            campaign_row = (
                await conn.execute(
                    text(
                        """
                        SELECT org_id, brand_id, created_by, brief->>'objective' AS objective
                        FROM campaigns WHERE id = CAST(:cid AS UUID)
                        """
                    ),
                    {"cid": campaign_id},
                )
            ).mappings().first()
            if campaign_row is not None:
                await notification_service.notify_campaign_published(
                    org_id=str(campaign_row["org_id"]),
                    brand_id=str(campaign_row["brand_id"]),
                    campaign_id=campaign_id,
                    created_by=str(campaign_row["created_by"]) if campaign_row["created_by"] else None,
                    title=campaign_row["objective"] or "Your campaign",
                )

    log.info("campaign_resumed", campaign_id=campaign_id, status=status)
    return status
