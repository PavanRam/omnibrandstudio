#!/usr/bin/env python
"""Submit the 50 RAG-grounded sample campaign briefs from docs/sample-campaign-briefs.md.

Defaults to a dry run: every brief is validated against CreateCampaignRequest
locally (no network calls). Pass --live to actually log in as the dev admin
and POST briefs to a running API — each live submission enqueues a REAL
worker run (content generation + up to 3 judges), so --limit defaults to 3
and must be raised explicitly for a larger batch.

Usage (from project root):
    uv run python backend/scripts/submit_sample_campaigns.py                  # dry run, all 50
    uv run python backend/scripts/submit_sample_campaigns.py --live --limit 3 # submit 3 for real
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from core.config import settings  # noqa: E402
from pipeline.schemas import CreateCampaignRequest  # noqa: E402

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEV_ADMIN_EMAIL = settings.DEV_ADMIN_EMAIL
DEV_ADMIN_PASSWORD = settings.DEV_ADMIN_PASSWORD

# Only brand with ingested RAG data locally (see docs/rag-ingest-verification.json).
BRAND_ID = "00000000-0000-0000-0000-000000000002"


def _b(
    objective: str,
    target_audience: str,
    key_messages: list[str],
    tone_override: str,
    channels: list[str],
    locales: list[str],
    audience_segments: list[str],
    end_date: str | None,
    raw_text: str,
) -> dict:
    return {
        "brand_id": BRAND_ID,
        "objective": objective,
        "target_audience": target_audience,
        "key_messages": key_messages,
        "tone_override": tone_override,
        "channels": channels,
        "locales": locales,
        "audience_segments": audience_segments,
        "end_date": end_date,
        "raw_text": raw_text,
    }


# ── Persona constants (from backend/data/datasets/processed/brand_guidelines/tone_voice_per_persona.json) ──

P1_TONE = "Premium, sophisticated, exclusive, confident"
P1_MSGS = [
    "You deserve the finest — and we deliver it.",
    "Exclusively curated for discerning tastes.",
    "Quality that speaks for itself.",
    "A world of premium products, personally selected for you.",
]
P1_CH = ["email", "instagram", "linkedin"]
P1_SEG = ["High-Income Store Spender"]

P2_TONE = "Reassuring, honest, helpful, straightforward"
P2_MSGS = [
    "Great quality doesn't have to cost more.",
    "Smart choices for everyday living.",
    "We respect your budget — and your intelligence.",
    "Real value, real savings, real results.",
]
P2_CH = ["email", "sms"]
P2_SEG = ["Budget-Conscious Low Spender"]

P3_TONE = "Modern, friendly, snappy, digitally native"
P3_MSGS = [
    "Shop smarter. Live better.",
    "Everything you need, right here, right now.",
    "Discover what's trending — curated just for you.",
    "Fast. Easy. Delivered to your door.",
]
P3_CH = ["instagram", "facebook", "twitter"]
P3_SEG = ["Web-Savvy Mid-Tier Buyer"]

P4_TONE = "Urgent, direct, deal-driven, energetic"
P4_MSGS = [
    "Today only — don't miss out.",
    "Your exclusive deal is waiting.",
    "Up to 50% off. Right now.",
    "Act fast — limited stock at this price.",
]
P4_CH = ["sms", "whatsapp", "facebook"]
P4_SEG = ["Deal-Seeking Value Hunter"]

P5_TONE = "Loyal, rewarding, inclusive, celebratory"
P5_MSGS = [
    "You've been with us from the start — here's something special.",
    "As one of our most valued customers, this is for you.",
    "Thank you for your loyalty. You deserve this.",
    "Exclusively for our most engaged community members.",
]
P5_CH = ["email", "instagram", "linkedin"]
P5_SEG = ["Highly Engaged Campaign Responder"]

# ── 50 briefs: mirrors docs/sample-campaign-briefs.md exactly — keep both in sync ──
SAMPLE_BRIEFS: list[dict] = [
    # Persona 1 — High-Income Store Spender
    _b("Launch the new limited-edition reserve wine and gourmet sweets collection to our highest-value store spenders, positioning it as a curated, exclusive addition to their pantry.",
       "High-Income Store Spender — wealthy, educated customers who shop in-store and spend heavily across all categories, with particular interest in premium wines, gourmet foods, and artisan sweets.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "fr"], P1_SEG, None,
       "Premium wine + gourmet collection just arrived — write this for our top in-store spenders. Keep it elegant, no discount talk, emphasize craftsmanship and limited availability."),
    _b("Re-engage high-value store spenders with a holiday gourmet foods & sweets gift box before the December gifting window closes.",
       "High-Income Store Spender, framed around holiday gifting for premium wines, gourmet foods, and artisan sweets.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "fr"], P1_SEG, "2026-12-24",
       "Holiday gift box campaign for our top spenders — frame as thoughtful gifting, not a sale."),
    _b("Introduce the autumn accessories capsule collection to high-income store spenders as an exclusive, limited-run addition to their wardrobe.",
       "High-Income Store Spender, with particular interest in curated fashion and accessories.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "fr", "es"], P1_SEG, "2026-10-15",
       "New capsule collection drop — premium tone, invite them to explore rather than push them to buy."),
    _b("Invite high-income store spenders back in-store for the end-of-season fashion event, framed as reserving final pieces rather than a clearance sale.",
       "High-Income Store Spender, end-of-season fashion and accessories.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "fr", "es"], P1_SEG, "2026-09-15",
       "End of season — do not use clearance/discount language for this segment; frame as limited final availability of curated pieces."),
    _b("Launch the new artisan home décor line to high-income store spenders, emphasizing craftsmanship and heritage.",
       "High-Income Store Spender, home décor and living essentials.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "es"], P1_SEG, None,
       "New artisan home line — lifestyle imagery, heritage story, no urgency language."),
    _b("Re-engage high-income store spenders with a cozy-season home living refresh, positioned as a seasonal curation rather than a promotion.",
       "High-Income Store Spender, seasonal home décor refresh.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "es"], P1_SEG, "2026-11-30",
       "Cozy season refresh — premium tone, invite to visit the store."),
    _b("Introduce the new premium wellness essentials line to high-income store spenders as a personally curated addition to their routine.",
       "High-Income Store Spender, premium health and wellness products.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "es"], P1_SEG, "2026-09-30",
       "New wellness line — no health claims beyond what's verified in the product spec sheet; keep it premium."),
    _b("Re-engage high-income store spenders with a New Year wellness reset curated specifically for them.",
       "High-Income Store Spender, New Year wellness reset.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US", "es"], P1_SEG, "2027-01-15",
       "New Year wellness campaign — reassuring, premium, avoid resolution clichés."),
    _b("Launch the next-gen smart home gadget line to high-income store spenders as a premium, design-led addition to their home.",
       "High-Income Store Spender, premium technology and gadgets.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US"], P1_SEG, None,
       "Smart home gadgets — premium design angle, not spec-sheet heavy."),
    _b("Invite high-income store spenders to an exclusive Black Friday preview of the smart home gadget line, framed as early access rather than a discount event.",
       "High-Income Store Spender, Black Friday tech preview.",
       P1_MSGS, P1_TONE, P1_CH, ["en-US"], P1_SEG, "2026-11-30",
       "Black Friday preview for top spenders — early access framing, not discount framing."),

    # Persona 2 — Budget-Conscious Low Spender
    _b("Introduce an affordable everyday wine and gourmet foods range to budget-conscious customers, leading with value and honesty.",
       "Budget-Conscious Low Spender — price-sensitive customers who spend minimally, interested in everyday-value wines and gourmet foods.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "fr"], P2_SEG, None,
       "New everyday-value food/wine range — plain, honest language, lead with price."),
    _b("Re-engage budget-conscious customers with a clearly-priced holiday gourmet foods bundle before December 24.",
       "Budget-Conscious Low Spender, holiday gourmet foods bundle.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "fr"], P2_SEG, "2026-12-24",
       "Holiday bundle — simple, transparent pricing, no jargon."),
    _b("Introduce an affordable autumn accessories capsule to budget-conscious buyers, emphasizing everyday practicality.",
       "Budget-Conscious Low Spender, affordable fashion and accessories.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "fr", "es"], P2_SEG, "2026-10-15",
       "Affordable accessories drop — short sentences, practical benefits."),
    _b("Bring budget-conscious customers back for the end-of-season fashion clearance with clear, honest savings messaging.",
       "Budget-Conscious Low Spender, end-of-season clearance.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "fr", "es"], P2_SEG, "2026-09-15",
       "Clearance event — lead with the savings number, keep it simple."),
    _b("Introduce an affordable home living essentials line to budget-conscious customers, focused on everyday value.",
       "Budget-Conscious Low Spender, affordable home essentials.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "es"], P2_SEG, None,
       "New affordable home line — practical scenarios, no jargon."),
    _b("Re-engage budget-conscious customers with a clearly-priced cozy-season home refresh bundle.",
       "Budget-Conscious Low Spender, cozy-season home refresh.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "es"], P2_SEG, "2026-11-30",
       "Cozy season bundle — simple, value-first."),
    _b("Introduce an affordable wellness essentials line to budget-conscious customers, focused on practical everyday benefits.",
       "Budget-Conscious Low Spender, affordable wellness essentials.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "es"], P2_SEG, "2026-09-30",
       "Affordable wellness line — no medical claims, simple honest tone."),
    _b("Re-engage budget-conscious customers with an affordable New Year wellness reset bundle.",
       "Budget-Conscious Low Spender, New Year wellness reset.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US", "es"], P2_SEG, "2027-01-15",
       "New Year wellness bundle — value-first, simple language."),
    _b("Introduce an affordable smart home gadget starter line to budget-conscious customers.",
       "Budget-Conscious Low Spender, affordable technology and gadgets.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US"], P2_SEG, None,
       "Starter gadget line — value framing, plain language, avoid spec jargon."),
    _b("Re-engage budget-conscious customers with a clearly-priced Black Friday gadget sale.",
       "Budget-Conscious Low Spender, Black Friday gadget sale.",
       P2_MSGS, P2_TONE, P2_CH, ["en-US"], P2_SEG, "2026-11-30",
       "Black Friday gadget sale — lead with price, simple and honest."),

    # Persona 3 — Web-Savvy Mid-Tier Buyer
    _b("Launch the new reserve wine and gourmet sweets collection to web-savvy mid-tier buyers with a digital-first, trend-forward campaign.",
       "Web-Savvy Mid-Tier Buyer — mid-income customers who prefer online shopping, interested in trending wines and gourmet sweets.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "fr"], P3_SEG, None,
       "New wine/sweets drop — punchy, short copy, strong visuals, social proof."),
    _b("Re-engage web-savvy mid-tier buyers with an online-exclusive holiday gourmet gift box promotion.",
       "Web-Savvy Mid-Tier Buyer, online-exclusive holiday gift box.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "fr"], P3_SEG, "2026-12-24",
       "Holiday gift box — online-exclusive angle, retargeting-friendly."),
    _b("Launch the autumn accessories capsule collection to web-savvy mid-tier buyers with trend-forward, shareable content.",
       "Web-Savvy Mid-Tier Buyer, trending fashion and accessories.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "fr", "es"], P3_SEG, "2026-10-15",
       "New capsule collection — short punchy copy, trending/new-arrival framing."),
    _b("Re-engage web-savvy mid-tier buyers with the end-of-season fashion clearance via a digital-first flash promotion.",
       "Web-Savvy Mid-Tier Buyer, digital flash clearance.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "fr", "es"], P3_SEG, "2026-09-15",
       "Clearance flash sale — snappy copy, strong CTA, retargeting."),
    _b("Launch the new artisan home décor line to web-savvy mid-tier buyers with trending, shareable social content.",
       "Web-Savvy Mid-Tier Buyer, trending home décor.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "es"], P3_SEG, None,
       "New home décor line — social-first, trending framing."),
    _b("Re-engage web-savvy mid-tier buyers with a cozy-season home living refresh promotion online.",
       "Web-Savvy Mid-Tier Buyer, cozy-season home refresh.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "es"], P3_SEG, "2026-11-30",
       "Cozy season refresh — online-exclusive, punchy copy."),
    _b("Launch the new wellness essentials line to web-savvy mid-tier buyers with a digital-first, trend-forward campaign.",
       "Web-Savvy Mid-Tier Buyer, trending wellness essentials.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "es"], P3_SEG, "2026-09-30",
       "Wellness line launch — trending framing, social proof, no medical claims."),
    _b("Re-engage web-savvy mid-tier buyers with a New Year wellness reset promotion online.",
       "Web-Savvy Mid-Tier Buyer, New Year wellness reset.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US", "es"], P3_SEG, "2027-01-15",
       "New Year wellness reset — snappy, trend-forward copy."),
    _b("Launch the next-gen smart home gadget line to web-savvy mid-tier buyers with a digital-first, feature-forward campaign.",
       "Web-Savvy Mid-Tier Buyer, trending technology and gadgets.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US"], P3_SEG, None,
       "Smart home gadgets — feature highlights, short punchy copy, social proof."),
    _b("Re-engage web-savvy mid-tier buyers with the Black Friday tech gadget sale via a digital-first flash promotion.",
       "Web-Savvy Mid-Tier Buyer, Black Friday tech sale.",
       P3_MSGS, P3_TONE, P3_CH, ["en-US"], P3_SEG, "2026-11-30",
       "Black Friday gadget sale — flash promotion, strong CTA, retargeting."),

    # Persona 4 — Deal-Seeking Value Hunter
    _b("Introduce the new wine and gourmet sweets range to deal-seeking value hunters with a launch discount to drive first purchase.",
       "Deal-Seeking Value Hunter — low-income customers who only engage with a compelling deal, targeted with a wine/gourmet sweets launch discount.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "fr"], P4_SEG, "2026-08-31",
       "Launch discount on new wine/sweets range — urgent, direct, lead with the offer."),
    _b("Re-engage deal-seeking value hunters with a time-limited holiday gourmet foods discount before December 24.",
       "Deal-Seeking Value Hunter, holiday gourmet foods discount.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "fr"], P4_SEG, "2026-12-24",
       "Holiday discount push — countdown framing, minimal copy."),
    _b("Launch the autumn accessories capsule to deal-seeking value hunters with an introductory limited-time discount.",
       "Deal-Seeking Value Hunter, discounted fashion and accessories.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "fr", "es"], P4_SEG, "2026-10-15",
       "New capsule intro discount — urgent, scarcity framing."),
    _b("Drive deal-seeking value hunters to the end-of-season fashion clearance with an aggressive, time-boxed discount push.",
       "Deal-Seeking Value Hunter, fashion clearance discount.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "fr", "es"], P4_SEG, "2026-09-15",
       "Clearance sale — biggest discount messaging, countdown urgency."),
    _b("Introduce the new home décor line to deal-seeking value hunters with an introductory discount offer.",
       "Deal-Seeking Value Hunter, discounted home décor.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "es"], P4_SEG, "2026-08-31",
       "New home line intro discount — urgent, direct."),
    _b("Re-engage deal-seeking value hunters with a cozy-season home living discount before November 30.",
       "Deal-Seeking Value Hunter, cozy-season home discount.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "es"], P4_SEG, "2026-11-30",
       "Cozy season discount push — countdown, minimal copy."),
    _b("Introduce the new wellness essentials line to deal-seeking value hunters with a launch discount.",
       "Deal-Seeking Value Hunter, discounted wellness essentials.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "es"], P4_SEG, "2026-09-30",
       "Wellness launch discount — urgent tone, no medical claims."),
    _b("Re-engage deal-seeking value hunters with a New Year wellness reset discount before January 15.",
       "Deal-Seeking Value Hunter, New Year wellness discount.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US", "es"], P4_SEG, "2027-01-15",
       "New Year wellness discount — countdown urgency."),
    _b("Introduce the smart home gadget line to deal-seeking value hunters with an introductory discount.",
       "Deal-Seeking Value Hunter, discounted technology and gadgets.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US"], P4_SEG, "2026-08-31",
       "Smart home gadget intro discount — urgent, direct, numbers-forward."),
    _b("Drive deal-seeking value hunters to the Black Friday tech gadget sale with maximum urgency messaging.",
       "Deal-Seeking Value Hunter, Black Friday gadget sale.",
       P4_MSGS, P4_TONE, P4_CH, ["en-US"], P4_SEG, "2026-11-30",
       "Black Friday gadget sale — biggest discount messaging, countdown."),

    # Persona 5 — Highly Engaged Campaign Responder
    _b("Give our most engaged customers early access to the new reserve wine and gourmet sweets collection as a loyalty reward.",
       "Highly Engaged Campaign Responder — the rarest, most responsive segment, offered early access to the new wine and gourmet sweets collection.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "fr"], P5_SEG, None,
       "Early access to new collection — reward the loyalty, reference their history with us."),
    _b("Reward highly engaged customers with an exclusive holiday gourmet gift box before December 24, celebrating their loyalty.",
       "Highly Engaged Campaign Responder, holiday loyalty gift box.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "fr"], P5_SEG, "2026-12-24",
       "Holiday loyalty gift box — warm, personal, thank-you framing."),
    _b("Give highly engaged customers early access to the autumn accessories capsule collection as a loyalty perk.",
       "Highly Engaged Campaign Responder, early access fashion capsule.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "fr", "es"], P5_SEG, "2026-10-15",
       "Early access capsule drop — personal, loyalty-first framing."),
    _b("Reward highly engaged customers with exclusive early access to the end-of-season fashion clearance before the public sale.",
       "Highly Engaged Campaign Responder, early-access fashion clearance.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "fr", "es"], P5_SEG, "2026-09-15",
       "Early access clearance — reward loyalty first, then the deal."),
    _b("Give highly engaged customers early access to the new artisan home décor line as a loyalty reward.",
       "Highly Engaged Campaign Responder, early access home décor line.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "es"], P5_SEG, None,
       "Early access home décor — celebratory, personal tone."),
    _b("Reward highly engaged customers with an exclusive cozy-season home living bundle.",
       "Highly Engaged Campaign Responder, cozy-season loyalty bundle.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "es"], P5_SEG, "2026-11-30",
       "Cozy season loyalty bundle — warm, appreciative tone."),
    _b("Give highly engaged customers early access to the new wellness essentials line as a loyalty reward.",
       "Highly Engaged Campaign Responder, early access wellness line.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "es"], P5_SEG, "2026-09-30",
       "Early access wellness line — loyalty-first, no medical claims."),
    _b("Reward highly engaged customers with an exclusive New Year wellness reset bundle, celebrating their loyalty.",
       "Highly Engaged Campaign Responder, New Year loyalty wellness bundle.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US", "es"], P5_SEG, "2027-01-15",
       "New Year loyalty wellness bundle — celebratory, appreciative tone."),
    _b("Give highly engaged customers early access to the next-gen smart home gadget line as a loyalty reward.",
       "Highly Engaged Campaign Responder, early access gadget line.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US"], P5_SEG, None,
       "Early access gadget line — loyalty-first framing."),
    _b("Reward highly engaged customers with exclusive early access to the Black Friday tech gadget sale before the public event.",
       "Highly Engaged Campaign Responder, early access Black Friday gadgets.",
       P5_MSGS, P5_TONE, P5_CH, ["en-US"], P5_SEG, "2026-11-30",
       "Early access Black Friday gadgets — reward loyalty first, then the deal."),
]

assert len(SAMPLE_BRIEFS) == 50, f"expected 50 sample briefs, got {len(SAMPLE_BRIEFS)}"


def validate_all() -> list[tuple[int, dict, ValidationError | None]]:
    results = []
    for i, brief in enumerate(SAMPLE_BRIEFS, start=1):
        try:
            CreateCampaignRequest(**brief)
            results.append((i, brief, None))
        except ValidationError as exc:
            results.append((i, brief, exc))
    return results


def login(client: httpx.Client) -> str:
    if not DEV_ADMIN_PASSWORD:
        sys.exit("DEV_ADMIN_PASSWORD not set in .env — required for --live submission.")
    resp = client.post(
        f"{API_BASE_URL}/auth/token",
        json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def submit(client: httpx.Client, token: str, brief: dict) -> dict:
    resp = client.post(
        f"{API_BASE_URL}/campaigns",
        json=brief,
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Actually submit to a running API (real pipeline runs, real cost).")
    parser.add_argument("--limit", type=int, default=3, help="Max briefs to submit when --live (default 3).")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between live submissions.")
    args = parser.parse_args()

    results = validate_all()
    failures = [(i, exc) for i, _, exc in results if exc is not None]
    print(f"Validated {len(results)} briefs against CreateCampaignRequest: {len(results) - len(failures)} passed, {len(failures)} failed.")
    for i, exc in failures:
        print(f"  brief #{i} FAILED: {exc}")
    if failures:
        return 1

    if not args.live:
        print("Dry run only (pass --live to actually submit). No network calls made.")
        return 0

    print(f"LIVE mode: submitting up to {args.limit} of 50 briefs to {API_BASE_URL} — this triggers real worker/LLM runs.")
    with httpx.Client(timeout=30.0) as client:
        token = login(client)
        for i, brief, _ in results[: args.limit]:
            outcome = submit(client, token, brief)
            print(f"  brief #{i} -> campaign_id={outcome['campaign_id']} poll_url={outcome['poll_url']}")
            time.sleep(args.sleep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
