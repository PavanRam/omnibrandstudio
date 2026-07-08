from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("/brand-guides")
async def upload_brand_guide() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "knowledge upload not yet implemented")


@router.get("/brand-guides/{brand_id}")
async def list_brand_guides(brand_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "knowledge list not yet implemented")
