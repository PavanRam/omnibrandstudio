from __future__ import annotations

import hashlib
from functools import lru_cache

import anyio


@lru_cache(maxsize=1)
def _get_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    return SentenceTransformer("all-MiniLM-L6-v2")


def _hash_embedding(text: str, dimensions: int = 384) -> list[float]:
    """Fallback deterministic embedding used when model loading is unavailable."""
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    out: list[float] = []
    for i in range(dimensions):
        byte = digest[i % len(digest)]
        out.append((byte / 255.0) * 2.0 - 1.0)
    return out


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = _get_sentence_transformer()
    if model is None:
        return [_hash_embedding(t) for t in texts]

    vectors = model.encode(texts, normalize_embeddings=True)
    return [list(map(float, row)) for row in vectors]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed text with local sentence-transformers using thread offload."""
    if not texts:
        return []
    return await anyio.to_thread.run_sync(_embed_sync, texts)
