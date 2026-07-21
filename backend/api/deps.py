from collections.abc import Callable
from dataclasses import dataclass, field

from core.database import get_db
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from api.middleware.auth import decode_access_token, hash_api_key, is_jti_revoked

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class UserContext:
    user_id: str
    org_id: str
    brand_ids: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    auth_method: str = "jwt"  # "jwt" | "api_key"


async def _authenticate_jwt(credentials: HTTPAuthorizationCredentials) -> UserContext:
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    jti = payload.get("jti")
    if jti and await is_jti_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")

    return UserContext(
        user_id=payload["sub"],
        org_id=payload["org_id"],
        brand_ids=payload.get("brand_ids", []),
        roles=payload.get("roles", []),
        auth_method="jwt",
    )


async def _authenticate_api_key(raw_key: str) -> UserContext:
    key_hash = hash_api_key(raw_key)
    async with get_db() as conn:
        result = await conn.execute(
            text(
                "SELECT org_id, brand_id, scopes FROM api_keys "
                "WHERE key_hash = :key_hash AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > NOW())"
            ),
            {"key_hash": key_hash},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")

    return UserContext(
        user_id="api_key",
        org_id=str(row["org_id"]),
        brand_ids=[str(row["brand_id"])] if row["brand_id"] else [],
        roles=list(row["scopes"] or []),
        auth_method="api_key",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_header),
) -> UserContext:
    if credentials is not None:
        return await _authenticate_jwt(credentials)
    if api_key is not None:
        return await _authenticate_api_key(api_key)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")


def require(*permissions: str) -> Callable[[UserContext], UserContext]:
    """RBAC dependency factory — checks the authenticated user's roles/scopes
    contain at least one of the required permissions."""

    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not set(permissions) & set(user.roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of: {', '.join(permissions)}",
            )
        return user

    return _check
