from __future__ import annotations

import hashlib

import httpx
import structlog
from core.config import settings
from pipeline.agents.base import traced_embedding_call

log = structlog.get_logger()


def embedding_collection_name(brand_id: str, kind: str) -> str:
    """Namespace collections so incompatible embedding spaces never mix."""
    space = settings.EMBEDDING_SPACE_ID.replace("-", "_")
    return f"brand_{brand_id}_{kind}_{space}_{settings.EMBEDDING_DIMENSIONS}"


def _hash_embedding(
    text: str,
    dimensions: int = settings.EMBEDDING_DIMENSIONS,
) -> list[float]:
    """Return a deterministic degraded-mode vector of the canonical size."""
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    return [
        ((digest[index % len(digest)] / 255.0) * 2.0) - 1.0
        for index in range(dimensions)
    ]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed through LiteLLM, with an explicit deterministic degraded mode."""
    if not texts:
        return []

    try:
        vectors, _usage = await traced_embedding_call(
            model=settings.EMBEDDING_MODEL_ALIAS,
            texts=texts,
            task="rag_embedding",
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        return vectors
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        log.warning(
            "embedding_hosted_failed_using_degraded_hash",
            model=settings.EMBEDDING_MODEL_ALIAS,
            dimensions=settings.EMBEDDING_DIMENSIONS,
            input_count=len(texts),
            error=str(exc),
        )
        return [
            _hash_embedding(text, dimensions=settings.EMBEDDING_DIMENSIONS)
            for text in texts
        ]
