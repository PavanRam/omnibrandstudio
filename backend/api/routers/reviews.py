"""T11 — human review API.

``GET /reviews``            list pending reviews (brand-scoped, paginated).
``POST /reviews/{id}/decide`` record a reviewer decision; when every review for
the campaign is decided, resume the paused graph.
"""
from __future__ import annotations

from typing import Annotated

import structlog
from core.database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pipeline.schemas import ReviewDecision
from services import review_service
from sqlalchemy import text

from api.deps import UserContext, require

router = APIRouter()
log = structlog.get_logger()

# Module-level dependency singletons (avoids B008 — calls in argument defaults).
_reviews_read = require("reviews:read", "campaigns:read")
_reviews_decide = require("reviews:decide", "campaigns:write")


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
