from __future__ import annotations

from typing import Any

import anyio
import numpy as np
from core.config import settings
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from services.rag.embeddings import embed_texts


class TFIDFReranker:
    """Lightweight primary reranker using TF-IDF cosine similarity."""

    async def score_all(self, query: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not docs:
            return docs

        texts = [doc["text"] for doc in docs]

        def _score() -> list[float]:
            vec = TfidfVectorizer(stop_words="english")
            tfidf = vec.fit_transform([query] + texts)
            scores = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
            return [float(s) for s in scores]

        scores = await anyio.to_thread.run_sync(_score)
        return [
            {**doc, "rerank_score": round(score, 4)}
            for doc, score in zip(docs, scores, strict=False)
        ]

    async def rerank(
        self,
        query: str,
        docs: list[dict[str, Any]],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        scored = await self.score_all(query, docs)
        ranked = sorted(
            scored,
            key=lambda doc: float(doc.get("rerank_score", doc.get("rrf_score", 0.0))),
            reverse=True,
        )
        if top_n is None:
            return ranked
        return ranked[:top_n]


class MMRReranker:
    """Maximal Marginal Relevance reranker for relevance/diversity balance."""

    def __init__(self, lambda_: float | None = None) -> None:
        self._lambda = settings.MMR_LAMBDA if lambda_ is None else lambda_

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 0.0 else 0.0

    async def rerank(
        self,
        query: str,
        docs: list[dict[str, Any]],
        top_n: int,
        lambda_param: float | None = None,
    ) -> list[dict[str, Any]]:
        if not docs:
            return docs
        if len(docs) <= top_n:
            return docs

        lam = self._lambda if lambda_param is None else lambda_param

        texts = [d["text"] for d in docs]
        query_emb = np.array((await embed_texts([query]))[0], dtype=float)
        doc_embs = [np.array(e, dtype=float) for e in await embed_texts(texts)]

        if "rerank_score" in docs[0]:
            raw = np.array([float(d.get("rerank_score", 0.0)) for d in docs], dtype=float)
            lo, hi = raw.min(), raw.max()
            if hi - lo > 1e-6:
                relevance = (raw - lo) / (hi - lo)
            else:
                relevance = np.array(
                    [self._cosine(query_emb, emb) for emb in doc_embs],
                    dtype=float,
                )
        else:
            relevance = np.array(
                [self._cosine(query_emb, emb) for emb in doc_embs],
                dtype=float,
            )

        selected: list[int] = []
        remaining: list[int] = list(range(len(docs)))

        for _ in range(min(top_n, len(docs))):
            best_idx = -1
            best_score = float("-inf")
            for i in remaining:
                max_sim = max(
                    (self._cosine(doc_embs[i], doc_embs[j]) for j in selected),
                    default=0.0,
                )
                mmr = lam * relevance[i] - (1.0 - lam) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i
            selected.append(best_idx)
            remaining.remove(best_idx)

        return [{**docs[i], "mmr_score": round(float(relevance[i]), 4)} for i in selected]
