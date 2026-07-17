from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.post("/token")
async def login() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "auth/token not yet implemented")


@router.post("/refresh")
async def refresh() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "auth/refresh not yet implemented")


@router.post("/logout")
async def logout() -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "auth/logout not yet implemented")
