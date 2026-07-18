import json
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry.propagate import inject
from sqlalchemy import text

from core.database import get_db
from core.ids import new_campaign_id
from core.redis import get_redis
from pipeline.schemas import CreateCampaignRequest

router = APIRouter()
log = structlog.get_logger()

QUEUE = "campaigns:queue"
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def _normalize_org_id(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except ValueError:
            return DEFAULT_ORG_ID
    return DEFAULT_ORG_ID


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_campaign(
    body: CreateCampaignRequest,
    request: Request,
) -> dict:
    """Create and immediately enqueue a campaign for processing.

    Returns 202 Accepted with the campaign_id.  Clients should poll
    GET /campaigns/{id}/status for progress.
    """
    campaign_id = new_campaign_id()
    request_id = getattr(request.state, "request_id", "")
    org_id = _normalize_org_id(getattr(request.state, "org_id", None))
    user_id = getattr(request.state, "user_id", "")

    brief_payload = body.model_dump()

    async with get_db() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO campaigns (id, org_id, brand_id, created_by, brief, status)
                VALUES (:id, :org_id, :brand_id, :created_by, CAST(:brief AS JSONB), :status)
                """
            ),
            {
                "id": campaign_id,
                "org_id": org_id,
                "brand_id": body.brand_id,
                "created_by": user_id or None,
                "brief": json.dumps(brief_payload),
                "status": "queued",
            },
        )
        await conn.commit()

    task = {
        "campaign_id": campaign_id,
        "org_id": org_id,
        "brand_id": body.brand_id,
        "user_id": user_id,
        "request_id": request_id,
        "brief": brief_payload,
    }
    trace_carrier: dict[str, str] = {}
    inject(trace_carrier)
    task["_trace_context"] = trace_carrier
    redis = get_redis()
    await redis.lpush(QUEUE, json.dumps(task))

    log.info(
        "campaign_enqueued",
        campaign_id=campaign_id,
        brand_id=body.brand_id,
        request_id=request_id,
    )
    return {
        "campaign_id": campaign_id,
        "status": "queued",
        "poll_url": f"/campaigns/{campaign_id}/status",
    }


@router.post("/{campaign_id}/run")
async def run_campaign(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns run not yet implemented")


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns get not yet implemented")


@router.get("/{campaign_id}/status")
async def get_campaign_status(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns status not yet implemented")
