"""BM25 keyword index and Reciprocal Rank Fusion for hybrid retrieval."""

import pickle
import re
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi

from src.utils.logger import get_logger

logger = get_logger("rag.hybrid")

# Increment this whenever the tokenization logic changes.
# Cached indices built with a different version are discarded and rebuilt.
_TOKENIZER_VERSION = 2

# ── NLTK resources (downloaded once, silently) ────────────────────────────────

import nltk  # noqa: E402

try:
    from nltk.corpus import stopwords as _sw_corpus
    _STOP_WORDS: frozenset[str] = frozenset(_sw_corpus.words("english"))
except LookupError:
    nltk.download("stopwords", quiet=True)
    from nltk.corpus import stopwords as _sw_corpus
    _STOP_WORDS = frozenset(_sw_corpus.words("english"))

from nltk.stem import PorterStemmer as _PorterStemmer  # noqa: E402

_STEMMER = _PorterStemmer()

# ── Tokenizer ─────────────────────────────────────────────────────────────────

_NON_ALPHA = re.compile(r"[^a-z0-9\s]")


def _tokenize(text: str) -> list[str]:
    """Normalise, remove stop words, and stem a text string.

    Steps:
      1. Lowercase and strip all non-alphanumeric characters.
      2. Split on whitespace.
      3. Drop stop words and single-character tokens.
      4. Apply Porter stemming so inflected forms share one token
         ("campaign", "campaigns", "campaigning" → "campaign").

    Must be used identically at index time and query time.
    """
    cleaned = _NON_ALPHA.sub(" ", text.lower())
    return [
        _STEMMER.stem(token)
        for token in cleaned.split()
        if token not in _STOP_WORDS and len(token) > 1
    ]


# ── BM25 index ────────────────────────────────────────────────────────────────

class HybridBM25Index:
    """BM25 index over a single ChromaDB collection's documents.

    Built lazily and cached in RAGRetriever — the first hybrid query
    triggers a full collection.get() and tokenisation.
    """

    def __init__(self, docs: list[dict]) -> None:
        # docs: list of {id, text, metadata}
        self._docs = docs
        tokenized = [_tokenize(d["text"]) for d in docs]
        self._bm25 = BM25Okapi(tokenized)
        logger.debug("BM25 index built over %d documents", len(docs))

    def save(self, path: Path, doc_count: int) -> None:
        """Serialize this index to disk using pickle.

        Stores the BM25Okapi object, the source docs list, the document
        count, and the tokenizer version for staleness detection on next load.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "bm25":              self._bm25,
                    "docs":              self._docs,
                    "doc_count":         doc_count,
                    "tokenizer_version": _TOKENIZER_VERSION,
                },
                f,
            )
        logger.debug("BM25 index saved to %s (%d docs)", path, doc_count)

    @classmethod
    def load(cls, path: Path) -> "tuple[HybridBM25Index, int] | None":
        """Load a previously saved index from disk.

        Returns (index, doc_count) if the file exists, is readable, and was
        built with the current tokenizer version.
        Returns None if the file is missing, corrupted, or version-mismatched
        (caller will trigger a fresh build).
        """
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            stored_version = data.get("tokenizer_version", 1)
            if stored_version != _TOKENIZER_VERSION:
                logger.info(
                    "BM25 cache at %s has tokenizer version %d (current: %d) — rebuilding",
                    path, stored_version, _TOKENIZER_VERSION,
                )
                return None
            instance = cls.__new__(cls)
            instance._bm25 = data["bm25"]
            instance._docs = data["docs"]
            logger.debug("BM25 index loaded from %s (%d docs)", path, data["doc_count"])
            return instance, data["doc_count"]
        except Exception as exc:
            logger.warning("BM25 cache at %s unreadable (%s) — will rebuild", path, exc)
            return None

    def query(
        self,
        query: str,
        n_results: int,
        where: Optional[dict] = None,
    ) -> list[dict]:
        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)

        candidates = [
            (self._docs[i], float(scores[i]))
            for i in range(len(self._docs))
            if self._matches_filter(self._docs[i]["metadata"], where)
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)

        return [
            {**doc, "bm25_score": score}
            for doc, score in candidates[:n_results]
        ]

    @staticmethod
    def _matches_filter(metadata: dict, where: Optional[dict]) -> bool:
        if not where:
            return True
        return all(metadata.get(k) == v for k, v in where.items())


def reciprocal_rank_fusion(
    vector_results: list[dict],
    bm25_results: list[dict],
    k: int = 60,
    n_results: int = 20,
) -> list[dict]:
    """Merge two ranked lists into one using RRF scoring.

    Both lists must contain dicts with at least 'text' and optionally 'id'.
    Result dicts carry an 'rrf_score' key for transparency.
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(vector_results):
        key = doc.get("id") or doc["text"][:60]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        doc_map[key] = doc

    for rank, doc in enumerate(bm25_results):
        key = doc.get("id") or doc["text"][:60]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in doc_map:
            doc_map[key] = doc

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**doc_map[key], "rrf_score": round(score, 6)}
        for key, score in ranked[:n_results]
    ]
