from __future__ import annotations

import os
import pickle
import re
import tempfile
from pathlib import Path
from typing import Any

import nltk
from rank_bm25 import BM25Okapi

_NON_ALPHA = re.compile(r"[^a-z0-9\s]")
_TOKENIZER_VERSION = 2


def _nltk_data_dir() -> Path:
    override = os.getenv("NLTK_DATA", "").strip()
    if override:
        candidate = Path(override)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            # Fall back when container/user cannot write configured path.
            pass
    for fallback in (Path.cwd() / ".nltk_data", Path(tempfile.gettempdir()) / "omnibrand_nltk_data"):
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            probe = fallback / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return fallback
        except OSError:
            continue
    # Last resort: return temp dir path even if write probe failed.
    return Path(tempfile.gettempdir()) / "omnibrand_nltk_data"


_FALLBACK_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "with",
    }
)

try:
    from nltk.corpus import stopwords as _sw_corpus

    _STOP_WORDS: frozenset[str] = frozenset(_sw_corpus.words("english"))
except LookupError:
    dl_dir = _nltk_data_dir()
    dl_dir_str = str(dl_dir)
    if dl_dir_str not in nltk.data.path:
        nltk.data.path.insert(0, dl_dir_str)
    try:
        nltk.download("stopwords", quiet=True, download_dir=dl_dir_str)
        from nltk.corpus import stopwords as _sw_corpus

        _STOP_WORDS = frozenset(_sw_corpus.words("english"))
    except Exception:
        _STOP_WORDS = _FALLBACK_STOP_WORDS

from nltk.stem import PorterStemmer

_STEMMER = PorterStemmer()


def _tokenize(text: str) -> list[str]:
    cleaned = _NON_ALPHA.sub(" ", text.lower())
    return [
        _STEMMER.stem(token)
        for token in cleaned.split()
        if token not in _STOP_WORDS and len(token) > 1
    ]


class HybridBM25Index:
    """BM25 index with save/load support and deterministic tokenization."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        tokenized = [_tokenize(d["text"]) for d in docs]
        self._bm25 = BM25Okapi(tokenized)

    def save(self, path: Path, doc_count: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "bm25": self._bm25,
                    "docs": self._docs,
                    "doc_count": doc_count,
                    "tokenizer_version": _TOKENIZER_VERSION,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path) -> tuple[HybridBM25Index, int] | None:
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if data.get("tokenizer_version", 1) != _TOKENIZER_VERSION:
                return None
            inst = cls.__new__(cls)
            inst._bm25 = data["bm25"]
            inst._docs = data["docs"]
            return inst, int(data["doc_count"])
        except Exception:
            return None

    def query(
        self,
        query: str,
        n_results: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)

        candidates: list[tuple[dict[str, Any], float]] = []
        for idx, doc in enumerate(self._docs):
            if not self._matches_filter(doc.get("metadata", {}), where):
                continue
            candidates.append((doc, float(scores[idx])))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return [{**doc, "bm25_score": score} for doc, score in candidates[:n_results]]

    @staticmethod
    def _matches_filter(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
        if not where:
            return True
        return all(metadata.get(k) == v for k, v in where.items())


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    bm25_results: list[dict[str, Any]],
    k: int = 60,
    n_results: int = 20,
) -> list[dict[str, Any]]:
    """Merge ranked lists with reciprocal-rank-fusion score."""
    scores: dict[str, float] = {}
    doc_map: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(vector_results):
        key = str(doc.get("id") or doc.get("text", "")[:60])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        doc_map[key] = doc

    for rank, doc in enumerate(bm25_results):
        key = str(doc.get("id") or doc.get("text", "")[:60])
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        doc_map.setdefault(key, doc)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**doc_map[key], "rrf_score": round(score, 6)}
        for key, score in ranked[:n_results]
    ]
