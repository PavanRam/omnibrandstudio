from __future__ import annotations

import httpx
import pytest
from core.config import settings
from pipeline.agents.base import traced_embedding_call
from services.rag import embeddings
from services.rag.reranker import TFIDFReranker


@pytest.mark.asyncio
async def test_traced_embedding_call_orders_and_validates_vectors(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{settings.LITELLM_BASE_URL}/embeddings",
        json={
            "model": "openai/text-embedding-3-small",
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ],
            "usage": {"prompt_tokens": 7},
            "_hidden_params": {"response_cost": 0.0001},
        },
    )

    vectors, usage = await traced_embedding_call(
        model="embedding",
        texts=["first", "second"],
        task="test_embedding",
        dimensions=2,
    )

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert usage["input_tokens"] == 7
    assert usage["model_resolved"] == "openai/text-embedding-3-small"
    request = httpx_mock.get_request()
    assert request is not None
    assert b'"dimensions":2' in request.content


@pytest.mark.asyncio
async def test_embed_texts_uses_canonical_hash_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _failed_call(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(embeddings, "traced_embedding_call", _failed_call)

    first = await embeddings.embed_texts(["same text"])
    second = await embeddings.embed_texts(["same text"])

    assert first == second
    assert len(first[0]) == settings.EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_tfidf_reranker_is_primary_and_orders_by_relevance() -> None:
    docs = [
        {"id": "unrelated", "text": "winter weather forecast"},
        {"id": "relevant", "text": "brand voice and brand vocabulary"},
    ]

    ranked = await TFIDFReranker().rerank("brand voice", docs)

    assert [doc["id"] for doc in ranked] == ["relevant", "unrelated"]
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]
