"""Re-rankers for post-retrieval result improvement.

Three implementations are provided:

CrossEncoderReranker  — neural (sentence-transformers ms-marco cross-encoder).
                        Tries local HuggingFace cache first; downloads on first
                        use if not cached.  Raises if both cache and network are
                        unavailable (e.g. corporate firewall).

TFIDFReranker         — TF-IDF cosine similarity.  Zero downloads, works fully
                        offline.  Used automatically by RAGRetriever as fallback
                        when the cross-encoder cannot be loaded.

MMRReranker           — Maximal Marginal Relevance.  Iteratively selects documents
                        that balance relevance to the query against diversity from
                        already-selected documents.  Uses rerank_score from a prior
                        CrossEncoder/TFIDF pass as the relevance signal when present;
                        falls back to query-doc cosine similarity otherwise.

All three expose rerank(query, docs, top_n).
CrossEncoderReranker and TFIDFReranker also expose score_all(query, docs) which
scores every candidate without truncating — used when MMR handles final selection.
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.rag.config import MMR_LAMBDA, RERANKER_MODEL
from src.utils.embeddings import get_encoder
from src.utils.logger import get_logger

logger = get_logger("rag.reranker")


class CrossEncoderReranker:
    """Neural (query, doc) scorer using a sentence-transformers CrossEncoder."""

    def __init__(self, model_name: str = RERANKER_MODEL) -> None:
        from sentence_transformers import CrossEncoder
        try:
            # Prefer the local cache — avoids any network call
            self._model = CrossEncoder(model_name, local_files_only=True)
            logger.info("Cross-encoder loaded from local cache: %s", model_name)
        except Exception:
            logger.info("Downloading cross-encoder: %s", model_name)
            self._model = CrossEncoder(model_name)
            logger.info("Cross-encoder ready")

    def score_all(self, query: str, docs: list[dict]) -> list[dict]:
        """Score every doc without truncating — feed the result into MMRReranker."""
        if not docs:
            return docs
        pairs = [(query, doc["text"]) for doc in docs]
        scores = self._model.predict(pairs)
        return [
            {**doc, "rerank_score": round(float(score), 4)}
            for doc, score in zip(docs, scores)
        ]

    def rerank(self, query: str, docs: list[dict], top_n: int) -> list[dict]:
        ranked = sorted(
            self.score_all(query, docs),
            key=lambda d: d["rerank_score"],
            reverse=True,
        )
        return ranked[:top_n]


class TFIDFReranker:
    """TF-IDF cosine similarity re-ranker — zero download, fully offline.

    Scores each (query, doc) pair by cosine similarity in TF-IDF space.
    Used automatically when the cross-encoder cannot be loaded.
    """

    def score_all(self, query: str, docs: list[dict]) -> list[dict]:
        """Score every doc without truncating — feed the result into MMRReranker."""
        if not docs:
            return docs
        texts = [doc["text"] for doc in docs]
        vec = TfidfVectorizer(stop_words="english")
        tfidf = vec.fit_transform([query] + texts)
        scores = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
        return [
            {**doc, "rerank_score": round(float(score), 4)}
            for doc, score in zip(docs, scores)
        ]

    def rerank(self, query: str, docs: list[dict], top_n: int) -> list[dict]:
        ranked = sorted(
            self.score_all(query, docs),
            key=lambda d: d["rerank_score"],
            reverse=True,
        )
        return ranked[:top_n]


class MMRReranker:
    """Maximal Marginal Relevance reranker.

    Iteratively selects documents that maximise:
        MMR(d) = λ · relevance(d, query) − (1−λ) · max sim(d, dⱼ)
                                                    j ∈ Selected

    Relevance signal: normalised rerank_score if present in docs (i.e. a prior
    CrossEncoder or TFIDF pass ran); otherwise query-doc cosine similarity.

    Diversity signal: cosine similarity between candidate and each already-selected
    document embedding (all-MiniLM-L6-v2, shared singleton from utils.embeddings).

    λ (lambda_) controls the trade-off:
      1.0 → pure relevance (equivalent to standard ranking)
      0.0 → pure diversity
      0.7 → recommended default
    """

    def __init__(self, lambda_: float = MMR_LAMBDA) -> None:
        self._lambda  = lambda_
        self._encoder = get_encoder()
        logger.info("MMRReranker ready — lambda=%.2f", lambda_)

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 0.0 else 0.0

    def rerank(self, query: str, docs: list[dict], top_n: int) -> list[dict]:
        if not docs:
            return docs
        if len(docs) <= top_n:
            return docs

        # Encode all documents and the query once up front
        texts     = [doc["text"] for doc in docs]
        query_emb = self._encoder.encode(query, convert_to_numpy=True)
        doc_embs  = self._encoder.encode(texts,  convert_to_numpy=True)

        # Build relevance vector: prefer prior rerank_score, fall back to cosine sim.
        # If all rerank_scores are identical (flat), normalization would produce all
        # zeros — fall back to cosine similarity so MMR can still rank by diversity.
        if "rerank_score" in docs[0]:
            raw = np.array([float(d["rerank_score"]) for d in docs])
            lo, hi = raw.min(), raw.max()
            if hi - lo > 1e-6:
                relevance = (raw - lo) / (hi - lo)
                logger.debug("MMRReranker: using normalised rerank_scores as relevance signal")
            else:
                relevance = np.array([
                    self._cosine(query_emb, doc_embs[i]) for i in range(len(docs))
                ])
                logger.debug(
                    "MMRReranker: flat rerank_scores (range=%.2e) — "
                    "falling back to cosine similarity", hi - lo,
                )
        else:
            relevance = np.array([
                self._cosine(query_emb, doc_embs[i]) for i in range(len(docs))
            ])
            logger.debug("MMRReranker: using cosine similarity as relevance signal")

        # Iterative MMR selection
        selected:  list[int] = []
        remaining: list[int] = list(range(len(docs)))

        for _ in range(min(top_n, len(docs))):
            best_idx   = -1
            best_score = float("-inf")

            for i in remaining:
                max_sim = (
                    max(self._cosine(doc_embs[i], doc_embs[j]) for j in selected)
                    if selected else 0.0
                )
                mmr = self._lambda * relevance[i] - (1.0 - self._lambda) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx   = i

            selected.append(best_idx)
            remaining.remove(best_idx)

        logger.debug(
            "MMRReranker: selected %d/%d docs (lambda=%.2f)",
            len(selected), len(docs), self._lambda,
        )
        return [
            {**docs[i], "mmr_score": round(float(relevance[i]), 4)}
            for i in selected
        ]
