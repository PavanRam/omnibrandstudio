#!/usr/bin/env python
"""
Local-testing-only poller for approving/rejecting directly in Airtable.

Airtable's Free plan can't run the "Send webhook" / "Run script" automation
actions, so Airtable can't push a reviewer's decision to our API. This script
does the reverse: it periodically pulls the Reviews table via Airtable's plain
REST API (not an Automation, so it isn't plan-gated) for rows a reviewer has
set to Approved/Rejected/Edited that haven't been synced back yet, and applies
each one through the *same* route an Airtable Automation would have called —
POST /reviews/{id}/airtable-decide. This script is a dumb HTTP client loop; it
contains no business logic of its own.

Usage:
    uv run python scripts/airtable_poll_reviews.py

Config (env vars, loaded from repo-root .env):
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE
        Already set for the outbound mirror; reused here to read the table.
    AIRTABLE_SYNC_API_KEY   REQUIRED. The raw value of the airtable:sync-scoped
        API key (e.g. "omnibrand-airtable-key" from the testing guide's seed
        SQL) — sent as X-API-Key when calling our own /airtable-decide route.
        Not the same value as AIRTABLE_API_KEY (that one authenticates to
        Airtable; this one authenticates to our own API).
    API_BASE_URL            default http://localhost:8000
    AIRTABLE_POLL_INTERVAL_SECONDS  default 15
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE = os.getenv("AIRTABLE_TABLE", "Reviews")
SYNC_API_KEY = os.getenv("AIRTABLE_SYNC_API_KEY", "")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
POLL_INTERVAL_SECONDS = int(os.getenv("AIRTABLE_POLL_INTERVAL_SECONDS", "15"))

# Rows a reviewer has actually decided on, that we haven't confirmed yet.
_FILTER_FORMULA = (
    "AND("
    "OR({Decision}='Approved',{Decision}='Rejected',{Decision}='Edited'),"
    "{Sync Status}!='Synced'"
    ")"
)


async def _fetch_actionable_records(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(
        f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE}",
        headers={"Authorization": f"Bearer {AIRTABLE_API_KEY}"},
        params={"filterByFormula": _FILTER_FORMULA},
    )
    resp.raise_for_status()
    return resp.json().get("records", [])


async def _apply_one(client: httpx.AsyncClient, record: dict) -> None:
    fields = record.get("fields", {})
    review_request_id = fields.get("review_request_id")
    if not review_request_id:
        print(f"[skip] {record['id']} has no review_request_id")
        return

    body = {
        "airtable_record_id": record["id"],
        "decision": fields.get("Decision", ""),
        "reviewer_note": fields.get("Reviewer Note"),
        "reviewer_email": fields.get("Reviewer Email"),
    }
    resp = await client.post(
        f"{API_BASE_URL}/reviews/{review_request_id}/airtable-decide",
        headers={"X-API-Key": SYNC_API_KEY, "Content-Type": "application/json"},
        json=body,
    )
    print(f"[{resp.status_code}] {review_request_id} decision={body['decision']!r} -> {resp.text[:200]}")


async def poll_forever() -> None:
    if not (AIRTABLE_API_KEY and AIRTABLE_BASE_ID):
        sys.exit("AIRTABLE_API_KEY / AIRTABLE_BASE_ID not set in .env - nothing to poll.")
    if not SYNC_API_KEY:
        sys.exit(
            "AIRTABLE_SYNC_API_KEY not set. Add it to .env with the raw value of "
            "the airtable:sync-scoped API key (e.g. 'omnibrand-airtable-key')."
        )

    print(
        f"Polling {AIRTABLE_BASE_ID}/{AIRTABLE_TABLE} every {POLL_INTERVAL_SECONDS}s "
        f"-> {API_BASE_URL} ... (Ctrl+C to stop)"
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            try:
                records = await _fetch_actionable_records(client)
                if records:
                    print(f"Found {len(records)} record(s) to sync")
                for record in records:
                    await _apply_one(client, record)
            except Exception as exc:  # best-effort loop - one bad tick shouldn't kill it
                print(f"[poll error] {exc}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(poll_forever())
