"""RAG (retrieval-augmented generation) service package.

The real Qdrant-backed retriever lives in ``services.rag.retriever`` and is
only available on branches where Qdrant/DB infrastructure is wired up.

This stub provides a ``get_retriever()`` factory so that import-time
resolution succeeds on the quick-eval / intake-agent branch.  All calls
degrade gracefully — ``get_examples`` in ``pipeline.agents.retrieval``
already catches any exception and returns an empty list.
"""
from __future__ import annotations


class _NullRetriever:
    """No-op retriever used when Qdrant is not available."""

    async def get_examples(
        self,
        brand_id: str,
        channel: str,
        locale: str,
        n: int = 3,
    ) -> list[str]:
        return []


_INSTANCE: _NullRetriever | None = None


def get_retriever() -> _NullRetriever:
    """Return a singleton null-retriever.

    Replace this with a real Qdrant-backed implementation on the develop
    branch once Qdrant is available.
    """
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = _NullRetriever()
    return _INSTANCE
