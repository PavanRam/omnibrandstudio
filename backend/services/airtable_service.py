"""Airtable review mirror: outbound sync + inbound write-back (config-gated, best-effort).

Postgres ``review_requests`` is the source of truth. ``sync_review`` upserts one row
per review request (keyed on ``review_request_id``, via Airtable's ``performUpsert``)
so a reviewer always sees a single, durable row to act on instead of a new row per
event. ``mark_synced`` is a direct single-record PATCH used by the inbound webhook
route to report validation failures (or confirm idempotent no-ops) back onto the
*same* Airtable record before a decision has actually been persisted — see
``api/routers/reviews.py::airtable_decide``.

Never raises: any failure logs an ``airtable_mirror_failed`` warning and returns
``False``, the same non-fatal policy as the cost-attribution / Langfuse writes in
``traced_llm_call``.
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


def _record_url(record_id: str) -> str:
    return f"{_url()}/{record_id}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }


async def sync_review(fields: dict) -> bool:
    """Upsert a review's row, keyed on ``review_request_id``.

    Used both when a review is first created (``Decision`` starts at ``"Pending"``)
    and after any decision is applied (Postman, the app UI, or Airtable itself) so
    the grid always reflects the current outcome. Requires ``review_request_id`` in
    ``fields`` — that's the merge key.
    """
    if not airtable_enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.patch(
                _url(),
                headers=_headers(),
                json={
                    "performUpsert": {"fieldsToMergeOn": ["review_request_id"]},
                    "records": [{"fields": fields}],
                },
            )
            resp.raise_for_status()
        return True
    except Exception as exc:  # best-effort mirror — never fatal
        log.warning(
            "airtable_mirror_failed", op="sync_review", ref=str(fields.get("review_request_id")),
            error=str(exc),
        )
        return False


async def mark_synced(record_id: str, *, status: str, error: str | None = None) -> bool:
    """PATCH a specific Airtable record's ``Sync Status``/``Sync Error`` by its
    Airtable record id (``rec...``). Used by the inbound webhook route to report a
    validation failure — or confirm an idempotent no-op — before/without a decision
    ever reaching :func:`services.review_service.apply_decision`."""
    if not airtable_enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.patch(
                _record_url(record_id),
                headers=_headers(),
                json={"fields": {"Sync Status": status, "Sync Error": error or ""}},
            )
            resp.raise_for_status()
        return True
    except Exception as exc:  # best-effort mirror — never fatal
        log.warning("airtable_mirror_failed", op="mark_synced", ref=record_id, error=str(exc))
        return False
