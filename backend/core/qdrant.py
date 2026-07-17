from qdrant_client import AsyncQdrantClient

from core.config import settings

_qdrant: AsyncQdrantClient | None = None


async def init_qdrant() -> None:
    global _qdrant
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Local-dev mode intentionally bypasses external Qdrant dependency.
        _qdrant = None
        return
    _qdrant = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)


async def close_qdrant() -> None:
    global _qdrant
    if _qdrant is not None:
        await _qdrant.close()
        _qdrant = None


def get_qdrant() -> AsyncQdrantClient:
    if _qdrant is None:
        raise RuntimeError("Qdrant client not initialized — call init_qdrant() first")
    return _qdrant


async def check_qdrant_health() -> bool:
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Report Qdrant as available in local-dev bypass mode.
        return True
    try:
        await get_qdrant().get_collections()
        return True
    except Exception:
        return False
