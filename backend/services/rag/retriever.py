from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import tempfile
from typing import Any

import structlog

from core.config import settings
from services.rag.hybrid import HybridBM25Index, reciprocal_rank_fusion
from services.rag.reranker import CrossEncoderReranker, MMRReranker, TFIDFReranker
from services.rag.vector_store import SearchResult, VectorStoreAdapter

log = structlog.get_logger()


@dataclass(slots=True)
class RetrievedChunk:
    id: str
    content: str
    score: float
    section_type: str
    version: str
    locale: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RAGRetriever:
    """Retriever pipeline: vector -> hybrid fuse -> rerank -> MMR."""

    def __init__(self, store: VectorStoreAdapter) -> None:
        self._store = store
        self._bm25_cache: dict[str, HybridBM25Index] = {}
        self._cross = CrossEncoderReranker()
        self._tfidf = TFIDFReranker()
        self._mmr = MMRReranker()
        self._bm25_cache_dir = self._resolve_writable_cache_dir()

    @staticmethod
    def _resolve_writable_cache_dir() -> Path:
        candidates = [
            Path(settings.BM25_CACHE_PATH),
            Path(tempfile.gettempdir()) / "omnibrand_bm25_cache",
        ]
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return candidate
            except OSError:
                continue
        return Path(tempfile.gettempdir()) / "omnibrand_bm25_cache"

    @staticmethod
    def _collection_name(brand_id: str, kind: str) -> str:
        return f"brand_{brand_id}_{kind}"

    @staticmethod
    def _to_doc(r: SearchResult) -> dict[str, Any]:
        return {
            "id": r.id,
            "text": r.text,
            "metadata": r.metadata,
            "score": r.score,
        }

    @staticmethod
    def _to_chunk(doc: dict[str, Any], locale: str) -> RetrievedChunk:
        meta = dict(doc.get("metadata", {}))
        return RetrievedChunk(
            id=str(doc.get("id", "")),
            content=str(doc.get("text", "")),
            score=float(doc.get("mmr_score", doc.get("rerank_score", doc.get("rrf_score", doc.get("score", 0.0))))),
            section_type=str(meta.get("section_type", "unknown")),
            version=str(meta.get("version", "unknown")),
            locale=str(meta.get("locale", locale)),
            metadata=meta,
        )

    @staticmethod
    def _build_where(brand_id: str, locale: str, extra_filters: dict[str, Any] | None) -> dict[str, Any]:
        where: dict[str, Any] = {
            "brand_id": brand_id,
            "locale": locale,
            "active": True,
        }
        if extra_filters:
            where.update(extra_filters)
        return where

    @staticmethod
    def _hybrid_cache_key(collection: str, locale: str, extra_filters: dict[str, Any] | None) -> str:
        section = extra_filters.get("section_type", "all") if extra_filters else "all"
        return f"{collection}:{locale}:{section}"

    @staticmethod
    def _filter_scoped_docs(
        docs: list[dict[str, Any]],
        *,
        brand_id: str,
        locale: str,
        extra_filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        section = extra_filters.get("section_type") if extra_filters else None
        scoped: list[dict[str, Any]] = []
        for doc in docs:
            meta = dict(doc.get("metadata", {}))
            if meta.get("brand_id") != brand_id:
                continue
            if meta.get("locale") != locale:
                continue
            if meta.get("active") is not True:
                continue
            if section is not None and meta.get("section_type") != section:
                continue
            scoped.append(doc)
        return scoped

    def _cache_path_for_key(self, cache_key: str) -> Path:
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        return self._bm25_cache_dir / f"bm25_{digest}.pkl"

    async def _get_bm25_documents(self, collection: str, where: dict[str, Any]) -> list[dict[str, Any]]:
        get_documents = getattr(self._store, "get_documents", None)
        if get_documents is None:
            return []
        docs_raw = await get_documents(collection=collection, filters=where)
        return [self._to_doc(d) for d in docs_raw]

    async def _get_bm25(
        self,
        *,
        cache_key: str,
        collection: str,
        where: dict[str, Any],
    ) -> HybridBM25Index | None:
        if cache_key in self._bm25_cache:
            return self._bm25_cache[cache_key]

        cache_path = self._cache_path_for_key(cache_key)
        docs = await self._get_bm25_documents(collection, where)
        current_count = len(docs)
        if current_count == 0:
            return None

        index = self._load_valid_cached_bm25(cache_path=cache_path, current_count=current_count)
        if index is None:
            index = self._rebuild_bm25(cache_path=cache_path, docs=docs, current_count=current_count)
        self._bm25_cache[cache_key] = index
        return index

    @staticmethod
    def _load_valid_cached_bm25(
        *,
        cache_path: Path,
        current_count: int,
    ) -> HybridBM25Index | None:
        cached = HybridBM25Index.load(cache_path)
        if cached is None:
            return None
        index, cached_count = cached
        if cached_count != current_count:
            return None
        return index

    @staticmethod
    def _rebuild_bm25(
        *,
        cache_path: Path,
        docs: list[dict[str, Any]],
        current_count: int,
    ) -> HybridBM25Index:
        index = HybridBM25Index(docs)
        try:
            index.save(cache_path, current_count)
        except OSError as exc:
            log.warning("bm25_cache_write_failed", path=str(cache_path), error=str(exc))
        return index

    async def _merge_candidates(
        self,
        *,
        collection: str,
        query: str,
        brand_id: str,
        locale: str,
        vector_docs: list[dict[str, Any]],
        where: dict[str, Any],
        pool_size: int,
        use_hybrid: bool,
        extra_filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not use_hybrid:
            return vector_docs

        cache_key = self._hybrid_cache_key(collection, locale, extra_filters)
        bm25_index = await self._get_bm25(
            cache_key=cache_key,
            collection=collection,
            where=where,
        )
        if bm25_index is None:
            log.info("hybrid_bm25_unavailable_fallback", collection=collection, brand_id=brand_id)
            return vector_docs

        bm25_results = bm25_index.query(query=query, n_results=pool_size, where=where)
        return reciprocal_rank_fusion(
            vector_results=vector_docs,
            bm25_results=bm25_results,
            k=settings.RRF_K,
            n_results=pool_size,
        )

    async def _rank_candidates(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        n_results: int,
        use_reranker: bool,
        use_mmr: bool,
    ) -> list[dict[str, Any]]:
        if use_reranker and use_mmr:
            scored = await self._score_all(query, candidates)
            if scored == candidates:
                scored = await self._tfidf_score_all(query, candidates)
            return await self._mmr_rerank(query, scored, n_results)

        if use_reranker:
            ranked = await self._cross_rerank(query, candidates, n_results)
            if ranked == candidates:
                return await self._tfidf_rerank(query, candidates, n_results)
            return ranked

        if use_mmr:
            return await self._mmr_rerank(query, candidates, n_results)

        return candidates[:n_results]

    async def _score_all(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        score_all = getattr(self._cross, "score_all", None)
        if callable(score_all):
            return await score_all(query, candidates)
        return await self._cross_rerank(query, candidates, len(candidates))

    async def _tfidf_score_all(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        score_all = getattr(self._tfidf, "score_all", None)
        if callable(score_all):
            return await score_all(query, candidates)
        return await self._tfidf_rerank(query, candidates, len(candidates))

    async def _cross_rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        try:
            return await self._cross.rerank(query, candidates, top_n=top_n)
        except TypeError:
            return await self._cross.rerank(query, candidates)

    async def _tfidf_rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        try:
            return await self._tfidf.rerank(query, candidates, top_n=top_n)
        except TypeError:
            return await self._tfidf.rerank(query, candidates)

    async def _mmr_rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        try:
            return await self._mmr.rerank(query, candidates, top_n=top_n)
        except TypeError:
            return await self._mmr.rerank(query, candidates, top_k=top_n)

    async def _query_collection(
        self,
        *,
        collection_kind: str,
        query: str,
        brand_id: str,
        locale: str,
        n_results: int,
        extra_filters: dict[str, Any] | None = None,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []

        where = self._build_where(brand_id, locale, extra_filters)

        collection = self._collection_name(brand_id, collection_kind)
        pool_size = fetch_k or settings.HYBRID_FETCH_K
        vector_hits = await self._store.query(
            collection=collection,
            query_text=query,
            filters=where,
            n_results=max(pool_size, n_results),
        )
        vector_docs = [self._to_doc(hit) for hit in vector_hits]
        vector_docs = self._filter_scoped_docs(
            vector_docs,
            brand_id=brand_id,
            locale=locale,
            extra_filters=extra_filters,
        )
        if not vector_docs:
            return []

        merged = await self._merge_candidates(
            collection=collection,
            query=query,
            brand_id=brand_id,
            locale=locale,
            vector_docs=vector_docs,
            where=where,
            pool_size=pool_size,
            use_hybrid=use_hybrid,
            extra_filters=extra_filters,
        )
        merged = self._filter_scoped_docs(
            merged,
            brand_id=brand_id,
            locale=locale,
            extra_filters=extra_filters,
        )
        if not merged:
            return []

        ranked = await self._rank_candidates(
            query=query,
            candidates=merged,
            n_results=n_results,
            use_reranker=use_reranker,
            use_mmr=use_mmr,
        )

        return [self._to_chunk(doc, locale=locale) for doc in ranked[:n_results]]

    async def retrieve(
        self,
        query: str,
        brand_id: str,
        locale: str,
        section_filter: str | None = None,
        n_results: int = 5,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int | None = None,
    ) -> list[RetrievedChunk]:
        extra = {"section_type": section_filter} if section_filter else None
        return await self._query_collection(
            collection_kind="guidelines",
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
            extra_filters=extra,
            use_hybrid=use_hybrid,
            use_reranker=use_reranker,
            use_mmr=use_mmr,
            fetch_k=fetch_k,
        )

    async def get_examples(self, brand_id: str, channel: str, locale: str, n: int = 3) -> list[str]:
        section = f"examples:{channel}"
        chunks = await self.retrieve(
            query=f"{channel} channel examples and brand voice guidance",
            brand_id=brand_id,
            locale=locale,
            section_filter=section,
            n_results=n,
        )
        if not chunks:
            chunks = await self.retrieve(
                query=f"{channel} brand copy examples",
                brand_id=brand_id,
                locale=locale,
                n_results=n,
            )
        return [chunk.content for chunk in chunks]

    async def query_customer_segments(
        self,
        query: str,
        brand_id: str,
        locale: str,
        n_results: int = 5,
    ) -> list[RetrievedChunk]:
        return await self._query_collection(
            collection_kind="segments",
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
        )

    async def query_campaign_data(
        self,
        query: str,
        brand_id: str,
        locale: str,
        n_results: int = 5,
    ) -> list[RetrievedChunk]:
        return await self._query_collection(
            collection_kind="campaigns",
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
        )

    async def query_sentiment_insights(
        self,
        query: str,
        brand_id: str,
        locale: str,
        n_results: int = 5,
    ) -> list[RetrievedChunk]:
        return await self._query_collection(
            collection_kind="sentiment",
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
        )
