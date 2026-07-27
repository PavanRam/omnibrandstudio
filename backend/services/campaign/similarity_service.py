"""Flags a likely-duplicate campaign before it's enqueued — purely advisory,
never blocking. Compares the new brief's objective+audience (semantic) and
its channels/audience_segments (structural overlap) against the brand's
recent campaigns.

Only ``failed`` campaigns are excluded from the candidate pool — everything
else (including a campaign still mid-run) is a valid match, since
re-triggering the same generation twice before the first one even finishes
is exactly the waste this is meant to catch.
"""
from __future__ import annotations

import math

from sqlalchemy import text

from core.database import get_db
from pipeline.conversation_models import PartialBrief, SimilarCampaignMatch

_CANDIDATE_LIMIT = 50
_MATCH_THRESHOLD = 0.90
_SEMANTIC_WEIGHT = 0.6
_CHANNEL_WEIGHT = 0.2
_SEGMENT_WEIGHT = 0.2


def _jaccard(a: list[str], b: list[str]) -> float:
    set_a = {x.lower() for x in a if x}
    set_b = {x.lower() for x in b if x}
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _brief_text(objective: str, target_audience: str) -> str:
    return f"{objective.strip()} {target_audience.strip()}".strip()


async def find_similar_campaign(
    *, brand_id: str, brief: PartialBrief
) -> SimilarCampaignMatch | None:
    query_text = _brief_text(brief.objective or "", brief.target_audience or "")
    if not query_text:
        return None

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, brief, status
                FROM campaigns
                WHERE brand_id = CAST(:brand_id AS UUID) AND status <> 'failed'
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"brand_id": brand_id, "limit": _CANDIDATE_LIMIT},
        )
        rows = result.mappings().all()

    if not rows:
        return None

    # Imported lazily so importing this module never pulls in the (optional)
    # sentence-transformers dependency unless a similarity check actually runs.
    from services.rag.embeddings import embed_texts

    candidate_texts = [query_text]
    for row in rows:
        candidate_brief = row["brief"] or {}
        candidate_texts.append(
            _brief_text(
                candidate_brief.get("objective", ""), candidate_brief.get("target_audience", "")
            )
        )

    vectors = await embed_texts(candidate_texts)
    query_vector, candidate_vectors = vectors[0], vectors[1:]

    best_match: SimilarCampaignMatch | None = None
    best_score = 0.0
    for row, vector in zip(rows, candidate_vectors, strict=True):
        candidate_brief = row["brief"] or {}
        semantic = _cosine(query_vector, vector)
        channel_overlap = _jaccard(brief.channels, candidate_brief.get("channels", []))
        segment_overlap = _jaccard(
            brief.audience_segments, candidate_brief.get("audience_segments", [])
        )
        score = (
            _SEMANTIC_WEIGHT * semantic
            + _CHANNEL_WEIGHT * channel_overlap
            + _SEGMENT_WEIGHT * segment_overlap
        )
        if score > best_score:
            best_score = score
            best_match = SimilarCampaignMatch(
                campaign_id=str(row["id"]),
                objective=candidate_brief.get("objective"),
                target_audience=candidate_brief.get("target_audience"),
                channels=candidate_brief.get("channels", []),
                status=str(row["status"]),
                score=score,
            )

    if best_match is not None and best_score >= _MATCH_THRESHOLD:
        return best_match
    return None
