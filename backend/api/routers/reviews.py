"""Human review API.

``GET /reviews``            list pending reviews (brand-scoped, paginated).
``POST /reviews/{id}/decide`` record a reviewer decision; when every review for
the campaign is decided, resume the paused graph.
"""
from __future__ import annotations

from typing import Annotated, Any

import structlog
from core.database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pipeline.schemas import ReviewDecision
from pydantic import ValidationError
from services import airtable_service, review_service
from sqlalchemy import text

from api.deps import UserContext, require

router = APIRouter()
log = structlog.get_logger()

# Module-level dependency singletons (avoids B008 — calls in argument defaults).
# Roles today are "admin" | "editor" | "viewer" | "reviewer" (see
# api/routers/users.py ALLOWED_ROLES) plus whatever scopes an API key carries;
# there is no separate "reviews:*"/"campaigns:*" permission system yet, so
# review access is granted directly to the roles that act on campaigns/reviews,
# with the scope strings kept as an extension point for future API-key-based
# access. "reviewer" is deliberately narrower than admin/editor: it can read
# and decide reviews, but (unlike admin/editor) is not treated as a campaign
# manager for send-to-review purposes — see campaigns.py's
# send_campaign_to_review endpoint.
_reviews_read = require("admin", "editor", "viewer", "reviewer", "reviews:read", "campaigns:read")
_reviews_decide = require("admin", "editor", "reviewer", "reviews:decide", "campaigns:write")
# Deliberately narrower than _reviews_decide: only a credential minted specifically
# for the Airtable integration (scope "airtable:sync") may call the webhook route,
# since that route is allowed to attribute a decision to a *different* user via
# reviewer_email — a capability that must not be reachable by every admin/editor
# API key or JWT, or any such caller could re-attribute decisions to someone else
# in the audit log.
_airtable_sync = require("airtable:sync")


@router.get("")
async def list_reviews(
    user: Annotated[UserContext, Depends(_reviews_read)],
    review_status: str = Query("pending", alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    params: dict = {"status": review_status, "limit": limit, "offset": offset}
    brand_clause = ""
    if user.brand_ids:
        brand_clause = "AND rr.brand_id = ANY(:brand_ids)"
        params["brand_ids"] = user.brand_ids

    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    f"""
                    SELECT rr.id AS review_request_id, rr.variant_id, rr.campaign_id,
                           rr.routing_reason, rr.status, rr.sla_deadline, rr.scores_snapshot,
                           cv.task_id, cv.locale, cv.channel, cv.segment,
                           COALESCE(cv.final_content, cv.personalized_content,
                                    cv.generated_content) AS content,
                           a.weighted_mean AS composite_score
                    FROM review_requests rr
                    JOIN content_variants cv ON cv.id = rr.variant_id
                    LEFT JOIN aggregated_scores a ON a.variant_id = rr.variant_id
                    WHERE rr.status = :status {brand_clause}
                    ORDER BY rr.created_at ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        ).mappings().all()

    return {
        "reviews": [
            {
                "review_request_id": str(r["review_request_id"]),
                "variant_id": str(r["variant_id"]),
                "campaign_id": str(r["campaign_id"]),
                "task_id": r["task_id"],
                "locale": r["locale"],
                "channel": r["channel"],
                "segment": r["segment"],
                "status": r["status"],
                "routing_reason": r["routing_reason"],
                "sla_deadline": r["sla_deadline"],
                "content": r["content"],
                "composite_score": (
                    float(r["composite_score"]) if r["composite_score"] is not None else None
                ),
                "scores_snapshot": r["scores_snapshot"],
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
        "count": len(rows),
    }


@router.post("/{review_request_id}/decide")
async def decide_review(
    review_request_id: str,
    body: ReviewDecision,
    response: Response,
    user: Annotated[UserContext, Depends(_reviews_decide)],
) -> dict:
    try:
        result = await review_service.apply_decision(
            review_request_id,
            body.decision,
            body.reviewer_note,
            body.edited_content,
            actor_id=user.user_id,
            brand_ids=user.brand_ids,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if not result["all_decided"]:
        # Other reviews for this campaign are still pending — stay paused.
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "review_request_id": review_request_id,
            "decision": body.decision,
            "status": "recorded",
            "campaign_status": "awaiting_review",
            "detail": "awaiting remaining reviews for this campaign",
        }

    campaign_status = await review_service.resume_campaign(result["campaign_id"])
    return {
        "review_request_id": review_request_id,
        "decision": body.decision,
        "status": "resumed",
        "campaign_status": campaign_status,
    }


@router.post("/{review_request_id}/airtable-decide")
async def airtable_decide(
    review_request_id: str,
    body: dict[str, Any],
    user: Annotated[UserContext, Depends(_airtable_sync)],
) -> dict:
    """Inbound webhook target for the Airtable Automation that fires when a
    reviewer sets the ``Decision`` dropdown to Approved/Rejected in the grid.

    Delegates to the same :func:`review_service.apply_decision` /
    :func:`review_service.resume_campaign` calls the human ``/decide`` route uses —
    this is a thin adapter, not a second decision pathway. What's different: every
    outcome (success, validation failure, already-decided) is written back onto the
    *same* Airtable record via ``airtable_record_id`` in the body, so a reviewer
    sees the result in the grid within seconds instead of needing Postman/logs.
    """
    airtable_record_id = body.get("airtable_record_id")
    if not airtable_record_id:
        log.warning("airtable_decide_missing_record_id", review_request_id=review_request_id)

    # Airtable's single-select values are capitalized ("Approved"); normalize here
    # rather than relying on the Automation's JSON-body template to do it.
    decision_value = str(body.get("decision", "")).strip().lower()
    body = {**body, "decision": decision_value}

    if decision_value == "edited":
        # Editing needs rewritten content, which a dropdown can't carry — out of
        # scope for the Airtable surface (see design doc §2).
        error = "Editing must be done via the app; use Approved or Rejected here."
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Error", error=error)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, error)

    try:
        decision_payload = ReviewDecision(**body)
    except ValidationError as exc:
        message = "; ".join(str(err["msg"]) for err in exc.errors())
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Error", error=message)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message) from exc

    # user.user_id is the trusted Airtable-integration service principal (the
    # caller authenticated with the narrow "airtable:sync" scope). Only override
    # it with a reviewer_email that actually resolves to a real user — never fall
    # back silently, or a typo would misattribute the decision without anyone
    # noticing.
    actor_id = user.user_id
    if decision_payload.reviewer_email:
        reviewer_email = decision_payload.reviewer_email
        resolved_actor = await review_service.resolve_reviewer_email(reviewer_email)
        if resolved_actor is None:
            error = f"reviewer_email '{reviewer_email}' does not match any known user"
            log.warning(
                "airtable_reviewer_email_unresolved",
                reviewer_email=decision_payload.reviewer_email,
                service_actor=user.user_id,
            )
            if airtable_record_id:
                await airtable_service.mark_synced(airtable_record_id, status="Error", error=error)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, error)
        log.info(
            "airtable_reviewer_email_resolved",
            reviewer_email=decision_payload.reviewer_email,
            service_actor=user.user_id,
            resolved_actor=resolved_actor,
        )
        actor_id = resolved_actor

    try:
        result = await review_service.apply_decision(
            review_request_id,
            decision_payload.decision,
            decision_payload.reviewer_note,
            None,
            actor_id=actor_id,
            brand_ids=user.brand_ids,
        )
    except LookupError as exc:
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Error", error=str(exc))
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Error", error=str(exc))
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError:
        # Already decided via another channel (e.g. Postman) — the other channel's
        # apply_decision() already synced this row, so this is an idempotent no-op.
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Synced")
        return {
            "review_request_id": review_request_id,
            "decision": decision_payload.decision,
            "status": "already_decided",
        }

    if not result["all_decided"]:
        if airtable_record_id:
            await airtable_service.mark_synced(airtable_record_id, status="Synced")
        return {
            "review_request_id": review_request_id,
            "decision": decision_payload.decision,
            "status": "recorded",
            "campaign_status": "awaiting_review",
        }

    campaign_status = await review_service.resume_campaign(result["campaign_id"])
    if airtable_record_id:
        await airtable_service.mark_synced(airtable_record_id, status="Synced")
    return {
        "review_request_id": review_request_id,
        "decision": decision_payload.decision,
        "status": "resumed",
        "campaign_status": campaign_status,
    }
