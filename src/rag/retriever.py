from typing import Optional

import chromadb

from src.rag.config import (
    BM25_CACHE_DIR,
    CHROMA_PATH,
    COLLECTION_BRAND,
    COLLECTION_CAMPAIGNS,
    COLLECTION_SEGMENTS,
    COLLECTION_SENTIMENT,
    HYBRID_FETCH_K,
    RRF_K,
)
from src.rag.hybrid import HybridBM25Index, reciprocal_rank_fusion
from src.rag.reranker import CrossEncoderReranker, MMRReranker, TFIDFReranker
from src.utils.logger import get_logger

logger = get_logger("rag.retriever")


class RAGRetriever:
    """Unified query interface for all four RAG knowledge base collections.

    Each public query method supports three retrieval modes, controlled by
    use_hybrid and use_reranker flags:

      - Pure vector (use_hybrid=False, use_reranker=False): original ChromaDB
        cosine similarity search.
      - Hybrid (use_hybrid=True): vector + BM25 keyword search merged via
        Reciprocal Rank Fusion.  Better for brand-rule lookups where exact
        terms matter.
      - Reranked (use_reranker=True): cross-encoder re-scores the merged
        candidate pool and returns the top_n by relevance.

    Both hybrid and reranker default to True.  BM25 indices and the
    cross-encoder model are initialised lazily on first use and cached.
    """

    def __init__(self) -> None:
        self._client    = chromadb.PersistentClient(path=CHROMA_PATH)
        self._brand     = self._client.get_collection(COLLECTION_BRAND)
        self._segments  = self._client.get_collection(COLLECTION_SEGMENTS)
        self._campaigns = self._client.get_collection(COLLECTION_CAMPAIGNS)
        self._sentiment = self._client.get_collection(COLLECTION_SENTIMENT)
        self._bm25_cache:   dict[str, HybridBM25Index]                          = {}
        self._reranker:     Optional[CrossEncoderReranker | TFIDFReranker]       = None
        self._mmr_reranker: Optional[MMRReranker]                                = None
        logger.info("RAGRetriever initialised — 4 collections ready")

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _format(results: dict) -> list[dict]:
        return [
            {"id": id_, "text": doc, "metadata": meta, "distance": dist}
            for id_, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    @staticmethod
    def _build_kwargs(
        query: str,
        n_results: int,
        collection_count: int,
        where: Optional[dict],
    ) -> dict:
        kwargs: dict = {
            "query_texts": [query],
            "n_results": min(n_results, collection_count),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            # ChromaDB requires $and operator when more than one filter is combined.
            # Single filter passes through as-is; multiple filters are wrapped.
            kwargs["where"] = (
                {"$and": [{k: {"$eq": v}} for k, v in where.items()]}
                if len(where) > 1
                else where
            )
        return kwargs

    def _get_bm25(self, collection) -> HybridBM25Index:
        """Return a BM25 index for the given collection.

        Load order:
        1. In-memory cache (same process, already built this session).
        2. Disk pickle (previous run) — valid if doc count matches ChromaDB.
        3. Full rebuild from ChromaDB — saves to disk for next restart.
        """
        name = collection.name
        if name not in self._bm25_cache:
            cache_path = BM25_CACHE_DIR / f"{name}.pkl"
            current_count = collection.count()

            cached = HybridBM25Index.load(cache_path)
            if cached is not None:
                index, cached_count = cached
                if cached_count == current_count:
                    logger.info(
                        "BM25 index for '%s' loaded from disk cache (%d docs)",
                        name, current_count,
                    )
                    self._bm25_cache[name] = index
                    return self._bm25_cache[name]
                logger.info(
                    "BM25 cache stale for '%s' (%d cached vs %d current) — rebuilding",
                    name, cached_count, current_count,
                )

            logger.info("Building BM25 index for '%s' ...", name)
            raw = collection.get(include=["documents", "metadatas"])
            docs = [
                {"id": id_, "text": doc, "metadata": meta}
                for id_, doc, meta in zip(
                    raw["ids"], raw["documents"], raw["metadatas"]
                )
            ]
            index = HybridBM25Index(docs)
            index.save(cache_path, current_count)
            logger.info(
                "BM25 index for '%s': %d docs indexed and saved to disk",
                name, len(docs),
            )
            self._bm25_cache[name] = index
        return self._bm25_cache[name]

    def _get_reranker(self) -> CrossEncoderReranker | TFIDFReranker:
        """Lazily load the reranker (cached after first call).

        Tries the neural cross-encoder first; falls back to the TF-IDF
        reranker if the model cannot be loaded (e.g. no network access).
        """
        if self._reranker is None:
            try:
                self._reranker = CrossEncoderReranker()
            except Exception as exc:
                logger.warning(
                    "Neural reranker unavailable (%s: %s) — using TF-IDF reranker.",
                    type(exc).__name__, exc,
                )
                self._reranker = TFIDFReranker()
        return self._reranker

    def _get_mmr_reranker(self) -> MMRReranker:
        if self._mmr_reranker is None:
            self._mmr_reranker = MMRReranker()
        return self._mmr_reranker

    def _execute_query(
        self,
        collection,
        query: str,
        n_results: int,
        where: Optional[dict],
        use_hybrid: bool,
        use_reranker: bool,
        use_mmr: bool,
        fetch_k: int,
    ) -> list[dict]:
        """Core pipeline: vector → (hybrid RRF) → (reranker) → (MMR) → top n_results.

        Combination behaviour:
          reranker=T, mmr=T  — cross-encoder scores all candidates; MMR selects
                               the diverse top_n from those scores.
          reranker=T, mmr=F  — cross-encoder scores and truncates to top_n.
          reranker=F, mmr=T  — MMR uses query-doc cosine similarity for relevance.
          reranker=F, mmr=F  — plain RRF/vector slice.
        """
        pool_size = fetch_k if (use_hybrid or use_reranker or use_mmr) else n_results

        vector_results = self._format(
            collection.query(
                **self._build_kwargs(query, pool_size, collection.count(), where)
            )
        )

        if use_hybrid:
            bm25_results = self._get_bm25(collection).query(query, fetch_k, where)
            merged = reciprocal_rank_fusion(
                vector_results, bm25_results, k=RRF_K, n_results=fetch_k
            )
        else:
            merged = vector_results

        if use_reranker and use_mmr:
            # Cross-encoder scores the full candidate pool (no truncation).
            # MMR then selects the diverse top_n from those scores.
            scored = self._get_reranker().score_all(query, merged)
            return self._get_mmr_reranker().rerank(query, scored, top_n=n_results)

        if use_reranker:
            return self._get_reranker().rerank(query, merged, top_n=n_results)

        if use_mmr:
            return self._get_mmr_reranker().rerank(query, merged, top_n=n_results)

        return merged[:n_results]

    # ── Public query methods ──────────────────────────────────────────────────

    def query_brand_guidelines(
        self,
        query: str,
        n_results: int = 5,
        persona: Optional[str] = None,
        channel: Optional[str] = None,
        language: Optional[str] = None,
        content_type: Optional[str] = None,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int = HYBRID_FETCH_K,
    ) -> list[dict]:
        """Retrieve brand rules, tone guidelines, channel templates, CTAs, compliance."""
        where: dict = {}
        if persona:
            where["persona"] = persona
        if channel:
            where["channel"] = channel
        if language:
            where["language"] = language
        if content_type:
            where["content_type"] = content_type
        return self._execute_query(
            self._brand, query, n_results, where or None,
            use_hybrid, use_reranker, use_mmr, fetch_k,
        )

    def query_customer_segments(
        self,
        query: str,
        n_results: int = 5,
        persona: Optional[str] = None,
        dominant_channel: Optional[str] = None,
        content_type: Optional[str] = None,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int = HYBRID_FETCH_K,
    ) -> list[dict]:
        """Retrieve customer profiles for persona-aware content personalisation.

        Pass content_type='persona_summary' to query only the 5 synthetic
        persona description documents (used for audience segment mapping).
        Pass content_type='customer_profile' to query only individual customer rows.
        Omit to query both.
        """
        where: dict = {}
        if persona:
            where["persona"] = persona
        if dominant_channel:
            where["dominant_channel"] = dominant_channel
        if content_type:
            where["content_type"] = content_type
        return self._execute_query(
            self._segments, query, n_results, where or None,
            use_hybrid, use_reranker, use_mmr, fetch_k,
        )

    def query_campaign_data(
        self,
        query: str,
        n_results: int = 5,
        channel: Optional[str] = None,
        language: Optional[str] = None,
        content_type: Optional[str] = None,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int = HYBRID_FETCH_K,
    ) -> list[dict]:
        """Retrieve campaign performance and ad data for channel/engagement context."""
        where: dict = {}
        if channel:
            where["channel"] = channel
        if language:
            where["language"] = language
        if content_type:
            where["content_type"] = content_type
        return self._execute_query(
            self._campaigns, query, n_results, where or None,
            use_hybrid, use_reranker, use_mmr, fetch_k,
        )

    def query_sentiment(
        self,
        query: str,
        n_results: int = 5,
        sentiment_label: Optional[str] = None,
        use_hybrid: bool = True,
        use_reranker: bool = True,
        use_mmr: bool = True,
        fetch_k: int = HYBRID_FETCH_K,
    ) -> list[dict]:
        """Retrieve individual tweets from the sentiment_insights collection.

        DEPRECATED for content generation use.
        Individual tweets are too short (3-15 words) and context-free to
        provide useful RAG context.  Use SentimentAnalyzer from
        src.rag.sentiment_stats instead — it returns aggregate stats
        (positive/negative split, peak hours, avg word count, tone signal)
        that are directly usable as LLM context in Phase 3.

        This method is retained for completeness and exploratory queries only.
        """
        logger.warning(
            "query_sentiment() returns individual tweets which are too short "
            "for useful RAG context. Use SentimentAnalyzer.tone_signal() instead."
        )
        where: dict = {}
        if sentiment_label:
            where["sentiment_label"] = sentiment_label
        return self._execute_query(
            self._sentiment, query, n_results, where or None,
            use_hybrid, use_reranker, use_mmr, fetch_k,
        )

    def query_all(self, query: str, n_results: int = 3) -> dict[str, list[dict]]:
        """Query the three content collections and return results keyed by name.

        Sentiment is intentionally excluded — individual tweets are not useful
        as retrieved documents.  For sentiment context use SentimentAnalyzer
        from src.rag.sentiment_stats.
        """
        return {
            "brand_guidelines":  self.query_brand_guidelines(query, n_results),
            "customer_segments": self.query_customer_segments(query, n_results),
            "campaign_data":     self.query_campaign_data(query, n_results),
        }
