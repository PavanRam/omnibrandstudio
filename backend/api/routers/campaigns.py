from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("")
async def create_campaign() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns create not yet implemented")


@router.post("/{campaign_id}/run")
async def run_campaign(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns run not yet implemented")


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns get not yet implemented")


@router.get("/{campaign_id}/status")
async def get_campaign_status(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns status not yet implemented")
