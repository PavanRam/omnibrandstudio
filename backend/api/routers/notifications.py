"""Notification bell API — every route is scoped to the caller's own
notifications (``recipient_user_id``), so any authenticated user/role may
call these; there's no separate permission to check beyond being logged in.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from services import notification_service

from api.deps import UserContext, get_current_user

router = APIRouter()

_current_user = Depends(get_current_user)


@router.get("")
async def list_notifications(
    user: Annotated[UserContext, _current_user],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    items = await notification_service.list_notifications(user.user_id, limit=limit, offset=offset)
    return {"notifications": items}


@router.get("/unread-count")
async def unread_count(user: Annotated[UserContext, _current_user]) -> dict:
    count = await notification_service.unread_count(user.user_id)
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: Annotated[UserContext, _current_user]) -> dict:
    ok = await notification_service.mark_read(user.user_id, notification_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(user: Annotated[UserContext, _current_user]) -> dict:
    updated = await notification_service.mark_all_read(user.user_id)
    return {"status": "ok", "updated": updated}
