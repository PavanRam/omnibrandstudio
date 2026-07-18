import json

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from core.ids import new_campaign_id
from core.redis import get_redis
from pipeline.schemas import CreateCampaignRequest

router = APIRouter()
log = structlog.get_logger()

QUEUE = "campaigns:queue"


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
    org_id = getattr(request.state, "org_id", "unknown")
    user_id = getattr(request.state, "user_id", "")

    task = {
        "campaign_id": campaign_id,
        "org_id": org_id,
        "brand_id": body.brand_id,
        "user_id": user_id,
        "request_id": request_id,
        "brief": body.model_dump(),
    }
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
