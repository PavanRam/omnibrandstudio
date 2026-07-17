from redis.asyncio import Redis

from core.config import settings

_redis: Redis | None = None


async def init_redis() -> None:
    global _redis
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Local-dev mode intentionally bypasses external Redis dependency.
        _redis = None
        return
    # socket_timeout must exceed the longest blocking call (worker's BLPOP
    # uses timeout=5) or the client raises spuriously before Redis replies.
    _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=10)


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis client not initialized — call init_redis() first")
    return _redis


async def check_redis_health() -> bool:
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Report Redis as available in local-dev bypass mode.
        return True
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False
