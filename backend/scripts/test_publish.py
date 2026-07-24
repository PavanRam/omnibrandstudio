"""Standalone smoke-test for the publishing agent.

Sends three styled demo emails (email, linkedin, sms channels) to the
address configured in PUBLISH_RECIPIENT_EMAILS via MailHog.

Usage (from project root):
    uv run python backend/scripts/test_publish.py

View results at http://localhost:8025
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make sure backend/ is on the path when run from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.agents.publishing import publishing_agent
from pipeline.state import OmniBrandState


def _make_state() -> OmniBrandState:
    variants = [
        {
            "task_id": "task-email-001",
            "channel": "email",
            "locale": "en-US",
            "segment": "enterprise",
            "status": "approved",
            "generated_content": None,
            "personalized_content": None,
            "final_content": (
                "Unlock the Future of Brand Storytelling\n\n"
                "Dear Creative Leader,\n\n"
                "We're thrilled to introduce OmniBrand Studio — the agentic content "
                "platform that turns a single campaign brief into fully personalised, "
                "brand-compliant content across every channel in minutes.\n\n"
                "✅ AI-generated, human-reviewed\n"
                "✅ Brand-score gated — only top content reaches your audience\n"
                "✅ Multi-locale, multi-segment out of the box\n\n"
                "Join 200+ marketing teams already shipping faster with OmniBrand.\n\n"
                "Best,\nThe OmniBrand Team"
            ),
            "translation_engine": None,
            "back_translation_score": None,
            "retry_count": 0,
            "reflexion_applied": False,
            "failure_reason": None,
            "translated_content": None,
            "generation_model": "gpt-4o",
            "prompt_version": "v1.2",
            "brand_guide_version": "2024-Q4",
        },
        {
            "task_id": "task-linkedin-001",
            "channel": "linkedin",
            "locale": "en-US",
            "segment": "enterprise",
            "status": "approved",
            "generated_content": None,
            "personalized_content": None,
            "final_content": (
                "🚀 Excited to share what we've been building at OmniBrand Studio!\n\n"
                "Marketing teams spend 60% of their time on content logistics — "
                "briefing, drafting, reviewing, translating, resizing. "
                "We built an agentic pipeline that does all of that in one shot.\n\n"
                "The result? Campaign content for 6 channels × 4 locales × 3 audience "
                "segments — scored against your brand guide — in under 5 minutes.\n\n"
                "We're opening early access next week. Drop a 🙋 in the comments if "
                "you want to be first in line.\n\n"
                "#AI #MarketingTech #ContentStrategy #GenAI #OmniBrandStudio"
            ),
            "translation_engine": None,
            "back_translation_score": None,
            "retry_count": 0,
            "reflexion_applied": False,
            "failure_reason": None,
            "translated_content": None,
            "generation_model": "gpt-4o",
            "prompt_version": "v1.2",
            "brand_guide_version": "2024-Q4",
        },
        {
            "task_id": "task-sms-001",
            "channel": "sms",
            "locale": "en-US",
            "segment": "enterprise",
            "status": "approved",
            "generated_content": None,
            "personalized_content": None,
            "final_content": (
                "OmniBrand: Your campaign is ready! 6 channels, 4 locales, brand-scored. "
                "Review now → omnibrandstudio.ai/demo"
            ),
            "translation_engine": None,
            "back_translation_score": None,
            "retry_count": 0,
            "reflexion_applied": False,
            "failure_reason": None,
            "translated_content": None,
            "generation_model": "gpt-4o",
            "prompt_version": "v1.2",
            "brand_guide_version": "2024-Q4",
        },
    ]

    aggregated_scores = [
        {
            "variant_id": "task-email-001",
            "weighted_mean": 8.4,
            "composite_score": 8.4,
            "routing_decision": "auto_approve",
            "judge_scores": [8.5, 8.2, 8.6],
            "critical_violations": [],
            "consensus_level": "strong_consensus",
            "degraded_mode": False,
        },
        {
            "variant_id": "task-linkedin-001",
            "weighted_mean": 7.9,
            "composite_score": 7.9,
            "routing_decision": "auto_approve",
            "judge_scores": [7.8, 8.1, 7.9],
            "critical_violations": [],
            "consensus_level": "moderate_consensus",
            "degraded_mode": False,
        },
        {
            "variant_id": "task-sms-001",
            "weighted_mean": 5.2,
            "composite_score": 5.2,
            "routing_decision": "flag",
            "judge_scores": [5.0, 5.5, 5.1],
            "critical_violations": ["Message too short — brand voice guideline requires ≥ 40 words"],
            "consensus_level": "weak_consensus",
            "degraded_mode": False,
        },
    ]

    brief = {
        "objective": "Drive early-access sign-ups for OmniBrand Studio launch",
        "target_audience": "VP/Director-level marketing leaders at enterprise SaaS companies",
        "key_messages": [
            "OmniBrand reduces content production time by 60%",
            "Brand-score gating ensures only compliant content ships",
            "Multi-locale, multi-channel, AI-native",
        ],
        "tone_override": "confident, data-driven, forward-looking",
        "channels": ["email", "linkedin", "sms"],
        "locales": ["en-US"],
        "audience_segments": ["enterprise"],
        "token_budget": 50000,
        "raw_text": "Launch campaign brief for OmniBrand Studio early access",
    }

    return OmniBrandState(
        campaign_id="demo-campaign-001",
        org_id="org-adobe-demo",
        brand_id="brand-omnibrand",
        user_id="user-ymahajan",
        started_at="2026-07-23T00:00:00",
        org_config={},
        brand_config={},
        model_aliases={},
        brief=brief,
        rag_context=None,
        prior_campaigns=[],
        brief_valid=True,
        brief_validation_errors=[],
        budget_check_passed=True,
        tasks=[],
        current_task=None,
        variants=variants,
        brand_scores=[],
        aggregated_scores=aggregated_scores,
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        current_phase="review_complete",
        human_review_requested=False,
        publishing_paused=False,
        token_cost_usd=1.24,
    )


async def main() -> None:
    print("=" * 60)
    print("OmniBrand Publishing Agent — smoke test")
    print("=" * 60)

    state = _make_state()
    print(f"\nCampaign : {state['campaign_id']}")
    print(f"Variants : {len(state['variants'])} ({', '.join(v['channel'] for v in state['variants'])})")

    from core.config import settings
    print(f"Recipient: {settings.PUBLISH_RECIPIENT_EMAILS}")
    print(f"SMTP     : {settings.PUBLISH_SMTP_HOST}:{settings.PUBLISH_SMTP_PORT}")
    print("\nDispatching …\n")

    result = await publishing_agent(state)

    receipts = result.get("publication_receipts", [])
    errors = result.get("errors", [])

    print(f"Phase    : {result.get('current_phase')}")
    print(f"Receipts : {len(receipts)}")
    print()
    for r in receipts:
        status_icon = "✅" if r["publish_status"] == "sent" else "❌"
        print(
            f"  {status_icon} [{r['channel'].upper():15s}] "
            f"{r['publish_status']:12s}  id={r['platform_publication_id']}"
        )
        if r.get("error_message"):
            print(f"      ↳ error: {r['error_message']}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  • {e}")

    print()
    if all(r["publish_status"] == "sent" for r in receipts):
        print("🎉 All variants sent.  Open http://localhost:8025 to review.")
    else:
        failed = [r for r in receipts if r["publish_status"] != "sent"]
        print(f"⚠️  {len(failed)} variant(s) failed — check SMTP connection.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
