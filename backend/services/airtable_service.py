"""T11 — Airtable outbound mirror (best-effort, config-gated).

Postgres ``review_requests`` is the source of truth; this only mirrors pending +
decided reviews into an Airtable table for reviewer visibility. It is a no-op
when Airtable is not configured and never raises — a mirror failure logs a
warning and returns ``False`` (same non-fatal policy as the cost-attribution /
Langfuse writes in ``traced_llm_call``).
"""
from __future__ import annotations

import httpx
import structlog
from core.config import settings

log = structlog.get_logger()

_TIMEOUT = 10.0


def airtable_enabled() -> bool:
    return bool(settings.AIRTABLE_API_KEY and settings.AIRTABLE_BASE_ID and settings.AIRTABLE_TABLE)


def _url() -> str:
    return f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{settings.AIRTABLE_TABLE}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }


async def _post(fields: dict, *, op: str, ref: str) -> bool:
    if not airtable_enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_url(), headers=_headers(), json={"fields": fields})
            resp.raise_for_status()
        return True
    except Exception as exc:  # best-effort mirror — never fatal
        log.warning("airtable_mirror_failed", op=op, ref=ref, error=str(exc))
        return False


async def upsert_review(review: dict) -> bool:
    """Mirror a pending review request into Airtable."""
    return await _post(
        {
            "review_request_id": review.get("review_request_id"),
            "campaign_id": review.get("campaign_id"),
            "variant_id": review.get("variant_id"),
            "status": review.get("status"),
            "routing_reason": review.get("routing_reason"),
        },
        op="upsert",
        ref=str(review.get("review_request_id")),
    )


async def patch_decision(review_request_id: str, decision: str, status: str) -> bool:
    """Mirror a reviewer decision (appended as a decision record)."""
    return await _post(
        {"review_request_id": review_request_id, "decision": decision, "status": status},
        op="decide",
        ref=review_request_id,
    )
