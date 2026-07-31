#!/usr/bin/env python
"""One-off E2E submission for the 2026-07-31 content_generator CTA-detection fix.

Mirrors backend/scripts/submit_sample_campaigns.py's login/submit flow but
posts a single brief (matches SAMPLE_BRIEFS persona-1 brief #4 exactly).
"""
from __future__ import annotations

import os
import sys

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEV_ADMIN_EMAIL = "admin@omnibrand.local"
DEV_ADMIN_PASSWORD = "E2eTemp2026Pass!"
BRAND_ID = "00000000-0000-0000-0000-000000000002"

BRIEF = {
    "brand_id": BRAND_ID,
    "objective": (
        "Invite high-income store spenders back in-store for the end-of-season "
        "fashion event, framed as reserving final pieces rather than a clearance sale."
    ),
    "target_audience": "High-Income Store Spender, end-of-season fashion and accessories.",
    "key_messages": [
        "You deserve the finest — and we deliver it.",
        "Exclusively curated for discerning tastes.",
        "Quality that speaks for itself.",
        "A world of premium products, personally selected for you.",
    ],
    "tone_override": (
        "Premium, sophisticated, exclusive, confident. Avoid: discount language, "
        "hard-sell urgency, informal tone"
    ),
    "channels": ["email", "instagram", "linkedin"],
    "locales": ["en-US", "fr", "es"],
    "audience_segments": ["High-Income Store Spender"],
    "end_date": "2026-09-15",
    "raw_text": (
        "End of season — do not use clearance/discount language for this segment; "
        "frame as limited final availability of curated pieces."
    ),
}


def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{API_BASE_URL}/auth/token",
            json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD},
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]

        resp = client.post(
            f"{API_BASE_URL}/campaigns",
            json=BRIEF,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        print(resp.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
