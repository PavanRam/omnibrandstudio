import hashlib
import time
import uuid

import bcrypt
from jose import JWTError, jwt

from core.config import settings
from core.redis import get_redis

LOCKOUT_MAX_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60


def create_access_token(*, user_id: str, org_id: str, roles: list[str], brand_ids: list[str]) -> str:
    now = int(time.time())
    payload = {
        "token_type": "access",
        "sub": user_id,
        "org_id": org_id,
        "roles": roles,
        "brand_ids": brand_ids,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, settings.private_key, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.public_key, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
    if payload.get("token_type") != "access":
        raise ValueError("Invalid token: wrong token type")
    return payload


def create_refresh_token(*, user_id: str, org_id: str) -> str:
    now = int(time.time())
    payload = {
        "token_type": "refresh",
        "sub": user_id,
        "org_id": org_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    }
    return jwt.encode(payload, settings.private_key, algorithm=settings.JWT_ALGORITHM)


def decode_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.public_key, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
    if payload.get("token_type") != "refresh":
        raise ValueError("Invalid token: wrong token type")
    return payload


async def is_jti_revoked(jti: str) -> bool:
    redis = get_redis()
    return bool(await redis.exists(f"revoked_jti:{jti}"))


async def revoke_jti(jti: str, ttl_seconds: int) -> None:
    redis = get_redis()
    await redis.set(f"revoked_jti:{jti}", "1", ex=ttl_seconds)


async def is_locked_out(email: str) -> bool:
    redis = get_redis()
    attempts = await redis.get(f"lockout:{email}")
    return attempts is not None and int(attempts) >= LOCKOUT_MAX_ATTEMPTS


async def record_failed_login(email: str) -> int:
    redis = get_redis()
    key = f"lockout:{email}"
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, LOCKOUT_WINDOW_SECONDS)
    return int(attempts)


async def clear_failed_logins(email: str) -> None:
    redis = get_redis()
    await redis.delete(f"lockout:{email}")


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_password(raw_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(raw_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
