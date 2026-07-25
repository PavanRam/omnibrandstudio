import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.deps import UserContext, get_current_user
from api.middleware.auth import (
    LOCKOUT_MAX_ATTEMPTS,
    clear_failed_logins,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    is_jti_revoked,
    is_locked_out,
    record_failed_login,
    revoke_jti,
    verify_password,
)
from core.config import settings
from core.database import get_db
from core.metrics import account_lockouts_total, auth_failures_total

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AuthUserProfile(BaseModel):
    user_id: str
    org_id: str
    email: str
    roles: list[str]
    brand_ids: list[str]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserProfile


def _normalize_uuid_list(raw: list[UUID] | None) -> list[str]:
    return [str(value) for value in (raw or [])]


def _normalized_roles(raw: list[str] | None) -> list[str]:
    return [value for value in (raw or []) if isinstance(value, str) and value]


async def _revoke_token_jti(payload: dict) -> None:
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, int):
        return
    ttl_seconds = max(1, exp - int(time.time()))
    await revoke_jti(jti, ttl_seconds)


def _invalid_credentials_error() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


async def _record_login_failure(email: str, reason: str) -> None:
    """Emit the auth-failure metric, register the attempt, and fire the lockout
    metric exactly once when this attempt crosses the lockout threshold."""
    auth_failures_total.labels(reason=reason).inc()
    attempts = await record_failed_login(email)
    if attempts == LOCKOUT_MAX_ATTEMPTS:
        account_lockouts_total.inc()


@router.post("/token")
async def login(body: LoginRequest) -> TokenResponse:
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid email")
    if await is_locked_out(email):
        auth_failures_total.labels(reason="locked_out").inc()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed login attempts. Try again later.",
        )

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, org_id, email, password_hash, roles, brand_ids, status
                FROM users
                WHERE lower(email) = :email
                LIMIT 1
                """
            ),
            {"email": email},
        )
        row = result.mappings().first()

        if row is None or row["status"] != "active":
            await _record_login_failure(
                email, "unknown_user" if row is None else "inactive_user"
            )
            raise _invalid_credentials_error()

        if not verify_password(body.password, str(row["password_hash"])):
            await _record_login_failure(email, "bad_password")
            raise _invalid_credentials_error()

        await conn.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE id = CAST(:user_id AS UUID)"),
            {"user_id": str(row["id"])},
        )
        await conn.commit()

    await clear_failed_logins(email)

    user_id = str(row["id"])
    org_id = str(row["org_id"])
    roles = _normalized_roles(row["roles"])
    brand_ids = _normalize_uuid_list(row["brand_ids"])

    access_token = create_access_token(
        user_id=user_id,
        org_id=org_id,
        roles=roles,
        brand_ids=brand_ids,
    )
    refresh_token = create_refresh_token(user_id=user_id, org_id=org_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=AuthUserProfile(
            user_id=user_id,
            org_id=org_id,
            email=str(row["email"]),
            roles=roles,
            brand_ids=brand_ids,
        ),
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest) -> TokenResponse:
    try:
        payload = decode_refresh_token(body.refresh_token)
    except ValueError as exc:
        auth_failures_total.labels(reason="invalid_token").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    jti = payload.get("jti")
    if isinstance(jti, str) and await is_jti_revoked(jti):
        auth_failures_total.labels(reason="revoked_jti").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")

    user_id = str(payload.get("sub", ""))
    org_id = str(payload.get("org_id", ""))

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, org_id, email, roles, brand_ids, status
                FROM users
                WHERE id = CAST(:user_id AS UUID)
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().first()

    if row is None or row["status"] != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user session")

    if str(row["org_id"]) != org_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token context")

    await _revoke_token_jti(payload)

    roles = _normalized_roles(row["roles"])
    brand_ids = _normalize_uuid_list(row["brand_ids"])

    access_token = create_access_token(
        user_id=str(row["id"]),
        org_id=str(row["org_id"]),
        roles=roles,
        brand_ids=brand_ids,
    )
    refresh_token = create_refresh_token(
        user_id=str(row["id"]),
        org_id=str(row["org_id"]),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=AuthUserProfile(
            user_id=str(row["id"]),
            org_id=str(row["org_id"]),
            email=str(row["email"]),
            roles=roles,
            brand_ids=brand_ids,
        ),
    )


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict:
    if user.auth_method != "jwt" or credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWT bearer token required")

    try:
        access_payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    await _revoke_token_jti(access_payload)

    if body.refresh_token:
        try:
            refresh_payload = decode_refresh_token(body.refresh_token)
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        await _revoke_token_jti(refresh_payload)

    return {"status": "logged_out"}
