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

ALLOWED_ROLES = {"admin", "editor", "viewer", "reviewer"}


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    role: Literal["admin", "editor", "viewer", "reviewer"]
    password: str | None = Field(default=None, min_length=8, max_length=256)
    # None (field omitted) preserves the old inherit-creator's-brands
    # default; an explicit list (including []) is used exactly as given —
    # an admin explicitly assigning zero brands is a deliberate org-wide
    # grant, not an accident (2026-07-27, multi-brand support).
    brand_ids: list[str] | None = None


class UpdateUserBrandsRequest(BaseModel):
    brand_ids: list[str]


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
    brand_ids = (
        _safe_brand_ids(body.brand_ids) if body.brand_ids is not None else _safe_brand_ids(current_user.brand_ids)
    )

    generated_password = body.password is None
    password = body.password or _new_temporary_password()
    password_hash = hash_password(password)

    async with get_db() as conn:
        if body.brand_ids is not None:
            await _validate_brand_ids_in_org(conn, current_user.org_id, brand_ids)
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


async def _validate_brand_ids_in_org(conn, org_id: str, brand_ids: list[str]) -> None:
    if not brand_ids:
        return
    result = await conn.execute(
        text("SELECT id FROM brands WHERE id = ANY(:brand_ids) AND org_id = :org_id"),
        {"brand_ids": brand_ids, "org_id": org_id},
    )
    found = {str(row["id"]) for row in result.mappings().all()}
    missing = [b for b in brand_ids if b not in found]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"brand(s) not found in your org: {missing}"
        )


@router.patch("/{user_id}/brands")
async def update_user_brands(
    user_id: str,
    body: UpdateUserBrandsRequest,
    current_user: Annotated[UserContext, Depends(require("admin"))],
) -> UserSummary:
    """Reassign which brand(s) a user is associated with — a fast-follow to
    item 44's brand-creation work (2026-07-27): brand_ids could only be set
    once at user-creation time (inherited from the creating admin) before
    this, with no way to change it afterward."""
    brand_ids = _safe_brand_ids(body.brand_ids)

    async with get_db() as conn:
        await _validate_brand_ids_in_org(conn, current_user.org_id, brand_ids)

        result = await conn.execute(
            text(
                """
                UPDATE users SET brand_ids = :brand_ids
                WHERE id = CAST(:user_id AS UUID) AND org_id = CAST(:org_id AS UUID)
                RETURNING id, email, roles, brand_ids, status, created_at, last_login_at
                """
            ),
            {"brand_ids": brand_ids, "user_id": user_id, "org_id": current_user.org_id},
        )
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in your org")

        await write_audit(
            db=conn,
            entity_type="user",
            action="users.update_brands",
            actor_id=_as_uuid_or_none(current_user.user_id),
            entity_id=str(row["id"]),
            org_id=current_user.org_id,
            before_val=None,
            after_val={"brand_ids": brand_ids},
        )
        await conn.commit()

    return UserSummary(
        user_id=str(row["id"]),
        email=str(row["email"]),
        roles=list(row["roles"] or []),
        brand_ids=[str(value) for value in (row["brand_ids"] or [])],
        status=str(row["status"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


class UpdateUserRequest(BaseModel):
    roles: list[Literal["admin", "editor", "viewer", "reviewer"]] | None = None
    brand_ids: list[str] | None = None
    status: Literal["active", "deactivated", "pending"] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: Annotated[UserContext, Depends(require("admin"))],
) -> UserSummary:
    """Update user properties: roles, status, brand assignments, or password."""
    async with get_db() as conn:
        # Load user first to verify ownership and collect "before" values
        res = await conn.execute(
            text("SELECT roles, brand_ids, status, password_hash FROM users WHERE id = CAST(:user_id AS UUID) AND org_id = CAST(:org_id AS UUID)"),
            {"user_id": user_id, "org_id": current_user.org_id}
        )
        existing = res.mappings().first()
        if not existing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in your org")

        updates = {}
        audit_after = {}

        if body.roles is not None:
            updates["roles"] = [r.strip().lower() for r in body.roles]
            audit_after["roles"] = updates["roles"]
        if body.brand_ids is not None:
            safe_brands = _safe_brand_ids(body.brand_ids)
            await _validate_brand_ids_in_org(conn, current_user.org_id, safe_brands)
            updates["brand_ids"] = safe_brands
            audit_after["brand_ids"] = safe_brands
        if body.status is not None:
            updates["status"] = body.status
            audit_after["status"] = body.status
        if body.password is not None:
            updates["password_hash"] = hash_password(body.password)
            audit_after["password_changed"] = True

        if not updates:
            return UserSummary(
                user_id=user_id,
                email="",
                roles=list(existing["roles"] or []),
                brand_ids=[str(v) for v in (existing["brand_ids"] or [])],
                status=str(existing["status"]),
                created_at=datetime.utcnow(),
            )

        # Build dynamic query
        set_clauses = [f"{col} = :{col}" for col in updates.keys()]
        query = f"""
            UPDATE users
            SET {", ".join(set_clauses)}
            WHERE id = CAST(:user_id AS UUID) AND org_id = CAST(:org_id AS UUID)
            RETURNING id, email, roles, brand_ids, status, created_at, last_login_at
        """
        
        params = {**updates, "user_id": user_id, "org_id": current_user.org_id}
        result = await conn.execute(text(query), params)
        row = result.mappings().one()

        await write_audit(
            db=conn,
            entity_type="user",
            action="users.update",
            actor_id=_as_uuid_or_none(current_user.user_id),
            entity_id=user_id,
            org_id=current_user.org_id,
            before_val={
                "roles": list(existing["roles"] or []),
                "brand_ids": [str(v) for v in (existing["brand_ids"] or [])],
                "status": existing["status"],
            },
            after_val=audit_after,
        )
        await conn.commit()

    return UserSummary(
        user_id=str(row["id"]),
        email=str(row["email"]),
        roles=list(row["roles"] or []),
        brand_ids=[str(value) for value in (row["brand_ids"] or [])],
        status=str(row["status"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )

