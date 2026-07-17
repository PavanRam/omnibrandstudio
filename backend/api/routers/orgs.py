from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("")
async def create_org() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "orgs create not yet implemented")


@router.get("/{org_id}")
async def get_org(org_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "orgs get not yet implemented")
