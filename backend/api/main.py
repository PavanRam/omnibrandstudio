from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import close_db, init_db
    from core.qdrant import close_qdrant, init_qdrant
    from core.redis import close_redis, init_redis

    await init_db()
    await init_redis()
    await init_qdrant()
    yield
    await close_db()
    await close_redis()
    await close_qdrant()


app = FastAPI(
    title="OmniBrand Studio API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import auth, campaigns, health, knowledge, orgs  # noqa: E402

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(orgs.router, prefix="/orgs", tags=["orgs"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
