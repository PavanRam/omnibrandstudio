from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from core.config import settings

_engine: AsyncEngine | None = None


async def init_db() -> None:
    global _engine
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Local-dev mode intentionally bypasses external DB dependency.
        _engine = None
        return
    _engine = create_async_engine(settings.POSTGRES_DSN, pool_pre_ping=True)


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized — call init_db() first")
    return _engine


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncConnection]:
    async with get_engine().connect() as conn:
        yield conn


async def check_db_health() -> bool:
    if settings.LOCAL_DEV_MODE:
        # TEMP_LOCAL_EVAL: Report DB as available in local-dev bypass mode.
        return True
    try:
        async with get_db() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
