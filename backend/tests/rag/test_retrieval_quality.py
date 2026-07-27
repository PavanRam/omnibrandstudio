from __future__ import annotations

from dataclasses import dataclass

import pytest

from pipeline.agents import stubs
from services.rag.retriever import RAGRetriever, RetrievedChunk
from services.rag.vector_store import SearchResult


@dataclass
class _FakeStore:
    last_collection: str | None = None
    last_filters: dict | None = None

    async def upsert(self, collection: str, points: list) -> None:  # pragma: no cover - not used
        return None

    async def query(self, collection: str, query_text: str, filters: dict, n_results: int) -> list[SearchResult]:
        self.last_collection = collection
        self.last_filters = filters

        brand_id = filters.get("brand_id")
        if brand_id == "brand-a":
            return [
                SearchResult(
                    id="a-1",
                    text="A brand voice rule",
                    score=0.91,
                    metadata={
                        "brand_id": "brand-a",
                        "locale": "en-US",
                        "section_type": filters.get("section_type", "guide"),
                        "version": "v2",
                        "active": True,
                    },
                )
            ]
        if brand_id == "brand-b":
            return [
                SearchResult(
                    id="b-1",
                    text="B brand voice rule",
                    score=0.93,
                    metadata={
                        "brand_id": "brand-b",
                        "locale": "en-US",
                        "section_type": filters.get("section_type", "guide"),
                        "version": "v5",
                        "active": True,
                    },
                )
            ]
        return []

    async def delete_by_filter(self, collection: str, filters: dict) -> None:  # pragma: no cover
        return None


class _NoopCross:
    async def rerank(self, query: str, docs: list[dict]):
        return docs


class _NoopTfidf:
    async def rerank(self, query: str, docs: list[dict]):
        return docs


class _NoopMmr:
    async def rerank(self, query: str, docs: list[dict], top_k: int, lambda_param: float = 0.7):
        return docs[:top_k]


@dataclass
class _LeakyStore:
    last_collection: str | None = None
    last_filters: dict | None = None

    async def upsert(self, collection: str, points: list) -> None:  # pragma: no cover - not used
        return None

    async def query(self, collection: str, query_text: str, filters: dict, n_results: int) -> list[SearchResult]:
        self.last_collection = collection
        self.last_filters = filters
        return [
            SearchResult(
                id="ok-a",
                text="Brand A active en-US",
                score=0.95,
                metadata={
                    "brand_id": "brand-a",
                    "locale": "en-US",
                    "section_type": filters.get("section_type", "guide"),
                    "version": "v2",
                    "active": True,
                },
            ),
            SearchResult(
                id="leak-b",
                text="Brand B leaked",
                score=0.99,
                metadata={
                    "brand_id": "brand-b",
                    "locale": "en-US",
                    "section_type": "guide",
                    "version": "v9",
                    "active": True,
                },
            ),
            SearchResult(
                id="wrong-locale",
                text="Brand A wrong locale",
                score=0.85,
                metadata={
                    "brand_id": "brand-a",
                    "locale": "fr-FR",
                    "section_type": "guide",
                    "version": "v2",
                    "active": True,
                },
            ),
            SearchResult(
                id="inactive",
                text="Brand A inactive",
                score=0.8,
                metadata={
                    "brand_id": "brand-a",
                    "locale": "en-US",
                    "section_type": "guide",
                    "version": "v1",
                    "active": False,
                },
            ),
        ]

    async def delete_by_filter(self, collection: str, filters: dict) -> None:  # pragma: no cover
        return None


def _fast_retriever(store: _FakeStore) -> RAGRetriever:
    retriever = RAGRetriever(store=store)
    retriever._cross = _NoopCross()  # type: ignore[attr-defined]
    retriever._tfidf = _NoopTfidf()  # type: ignore[attr-defined]
    retriever._mmr = _NoopMmr()  # type: ignore[attr-defined]
    return retriever


@pytest.mark.asyncio
async def test_retrieve_normalizes_bare_locale_code_to_seeded_bcp47_tag() -> None:
    """Regression (2026-07-26): callers pass whatever locale format the brief
    was captured in (e.g. bare "en"), but seeded guideline data is tagged
    "en-US". Chroma's `where` filter is an exact match, so a bare short code
    silently found zero chunks and every judge call fell back to "no brand
    guide" — a critical violation that auto-rejected every English variant."""
    store = _FakeStore()
    retriever = _fast_retriever(store)

    chunks = await retriever.retrieve(
        query="brand voice",
        brand_id="brand-a",
        locale="en",
        n_results=3,
    )

    assert store.last_filters["locale"] == "en-US"
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_retrieve_scopes_collection_and_filters_by_brand() -> None:
    store = _FakeStore()
    retriever = _fast_retriever(store)

    chunks = await retriever.retrieve(
        query="brand voice",
        brand_id="brand-a",
        locale="en-US",
        n_results=3,
    )

    assert store.last_collection == "brand_brand-a_guidelines"
    assert store.last_filters is not None
    assert store.last_filters["brand_id"] == "brand-a"
    assert len(chunks) == 1
    assert chunks[0].metadata["brand_id"] == "brand-a"


@pytest.mark.asyncio
async def test_retrieve_applies_section_filter() -> None:
    store = _FakeStore()
    retriever = _fast_retriever(store)

    await retriever.retrieve(
        query="email examples",
        brand_id="brand-a",
        locale="en-US",
        section_filter="examples:email",
        n_results=2,
    )

    assert store.last_filters is not None
    assert store.last_filters["section_type"] == "examples:email"


@pytest.mark.asyncio
async def test_query_customer_segments_uses_brand_scoped_collection() -> None:
    store = _FakeStore()
    retriever = _fast_retriever(store)

    await retriever.query_customer_segments(
        query="enterprise segments",
        brand_id="brand-a",
        locale="en-US",
        n_results=2,
    )

    assert store.last_collection == "brand_brand-a_segments"
    assert store.last_filters is not None
    assert store.last_filters["brand_id"] == "brand-a"
    assert store.last_filters["locale"] == "en-US"
    assert store.last_filters["active"] is True


@pytest.mark.asyncio
async def test_retrieve_filters_cross_tenant_and_out_of_scope_docs() -> None:
    store = _LeakyStore()
    retriever = _fast_retriever(store)

    chunks = await retriever.retrieve(
        query="brand voice",
        brand_id="brand-a",
        locale="en-US",
        n_results=5,
    )

    assert len(chunks) == 1
    assert chunks[0].id == "ok-a"
    assert chunks[0].metadata["brand_id"] == "brand-a"
    assert chunks[0].metadata["locale"] == "en-US"
    assert chunks[0].metadata["active"] is True


class _FakeRetriever:
    async def retrieve(self, **kwargs) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                id="1",
                content="chunk one",
                score=0.9,
                section_type="guide",
                version="v2",
                locale="en-US",
                metadata={},
            ),
            RetrievedChunk(
                id="2",
                content="chunk two",
                score=0.8,
                section_type="examples:email",
                version="v10",
                locale="en-US",
                metadata={},
            ),
        ]


@pytest.mark.asyncio
async def test_intake_rag_context_uses_latest_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stubs, "get_retriever", lambda: _FakeRetriever())

    state = {
        "campaign_id": "camp-1",
        "brand_id": "brand-a",
        "brief": {
            "objective": "Increase conversions",
            "raw_text": "",
            "locales": ["en-US"],
        },
    }
    result = await stubs.intake_agent_stub(state)  # type: ignore[arg-type]

    assert result["rag_context"] is not None
    assert result["rag_context"]["brand_guide_version"] == "v10"
