import secrets
import string
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.deps import UserContext, require
from api.middleware.auth import hash_password
from core.database import get_db
from services.audit_service import write_audit

router = APIRouter()

ALLOWED_ROLES = {"admin", "editor", "viewer"}


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    role: Literal["admin", "editor", "viewer"]
    password: str | None = Field(default=None, min_length=8, max_length=256)


class UserSummary(BaseModel):
    user_id: str
    email: str
    roles: list[str]
    brand_ids: list[str]
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class ListUsersResponse(BaseModel):
    count: int
    items: list[UserSummary]


class CreateUserResponse(BaseModel):
    user: UserSummary
    temporary_password: str | None = None


def _normalized_email(raw: str) -> str:
    email = raw.strip().lower()
    if "@" not in email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid email")
    return email


def _safe_brand_ids(raw_brand_ids: list[str]) -> list[str]:
    safe: list[str] = []
    for value in raw_brand_ids:
        try:
            safe.append(str(UUID(str(value))))
        except (ValueError, TypeError):
            continue
    return safe


def _new_temporary_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _as_uuid_or_none(value: str) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        return None


@router.get("")
async def list_users(
    current_user: Annotated[UserContext, Depends(require("admin"))],
) -> ListUsersResponse:
    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, email, roles, brand_ids, status, created_at, last_login_at
                FROM users
                WHERE org_id = CAST(:org_id AS UUID)
                  AND status != 'deleted'
                ORDER BY created_at DESC
                """
            ),
            {"org_id": current_user.org_id},
        )
        rows = result.mappings().all()

    items = [
        UserSummary(
            user_id=str(row["id"]),
            email=str(row["email"]),
            roles=list(row["roles"] or []),
            brand_ids=[str(value) for value in (row["brand_ids"] or [])],
            status=str(row["status"]),
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )
        for row in rows
    ]
    return ListUsersResponse(count=len(items), items=items)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user: Annotated[UserContext, Depends(require("admin"))],
) -> CreateUserResponse:
    role = body.role.strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported role")

    email = _normalized_email(body.email)
    brand_ids = _safe_brand_ids(current_user.brand_ids)

    generated_password = body.password is None
    password = body.password or _new_temporary_password()
    password_hash = hash_password(password)

    async with get_db() as conn:
        try:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO users (org_id, email, password_hash, roles, brand_ids, status)
                    VALUES (CAST(:org_id AS UUID), :email, :password_hash, :roles, :brand_ids, 'active')
                    RETURNING id, email, roles, brand_ids, status, created_at, last_login_at
                    """
                ),
                {
                    "org_id": current_user.org_id,
                    "email": email,
                    "password_hash": password_hash,
                    "roles": [role],
                    "brand_ids": brand_ids,
                },
            )
            row = result.mappings().one()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "User already exists") from exc

        await write_audit(
            db=conn,
            entity_type="user",
            action="users.create",
            actor_id=_as_uuid_or_none(current_user.user_id),
            entity_id=str(row["id"]),
            org_id=current_user.org_id,
            before_val=None,
            after_val={
                "name": body.name,
                "email": email,
                "roles": [role],
                "brand_ids": brand_ids,
                "status": "active",
            },
        )
        await conn.commit()

    user = UserSummary(
        user_id=str(row["id"]),
        email=str(row["email"]),
        roles=list(row["roles"] or []),
        brand_ids=[str(value) for value in (row["brand_ids"] or [])],
        status=str(row["status"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )

    return CreateUserResponse(
        user=user,
        temporary_password=password if generated_password else None,
    )
