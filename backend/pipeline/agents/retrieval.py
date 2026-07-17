from __future__ import annotations

import structlog
from services.rag import get_retriever

log = structlog.get_logger()

# Few-shot example retrieval. Signature matches T3.2's original stub exactly
# (get_examples(brand_id, channel, locale, n) -> list[str]), so content_generator.py
# needed no changes when this switched from a static in-code dict to a real
# Qdrant-backed hybrid search (see services/rag/retriever.py).


async def get_examples(brand_id: str, channel: str, locale: str, n: int = 3) -> list[str]:
    """Returns up to n few-shot example strings for a channel.

    Few-shot examples are a quality enhancement, not a hard requirement --
    content_generator's prompt already renders "(none available)" when the
    list is empty. So a Qdrant/embedding-service outage degrades quietly to
    no examples rather than failing the whole content_generator node (which
    safe_agent_run would otherwise turn into a zero-variant error state for
    every task, not just a missing few-shot enhancement).
    """
    try:
        return await get_retriever().get_examples(brand_id, channel, locale, n)
    except Exception as exc:
        log.warning("get_examples_failed", channel=channel, locale=locale, error=str(exc))
        return []
