from fastapi import APIRouter

from core.database import check_db_health
from core.redis import check_redis_health

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    overall_ok = db_ok and redis_ok

    return {
        "status": "healthy" if overall_ok else "degraded",
        "checks": {
            "database": {"status": "up" if db_ok else "down"},
            "redis": {"status": "up" if redis_ok else "down"},
        },
    }


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict:
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    return {"status": "ready" if (db_ok and redis_ok) else "not_ready"}
