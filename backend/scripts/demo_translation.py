"""Local demo for the Translation Agent — real Claude + real HF calls, zero
Docker infra.

Shows the full gate: Claude primary translation -> mBART independent
reference -> locale-dedicated back-translation -> BLEU / semantic-similarity /
cosine checks -> pass or fail-closed escalation.

Needs (both real, no infra):
    ANTHROPIC_API_KEY   -- primary translation + back-translation fallback
    HF_TOKEN            -- mBART / Helsinki-NLP / MPNet via HF Inference Providers

Runs three cases (per the build brief's demo runbook):
    1. Clean pass, EN -> es-MX
    2. Clean pass, EN -> fr-FR (multi-locale coverage)
    3. Deliberate failure case -- content shaped to diverge from a literal
       reference translation, to prove the escalation path fires live.

Run from the backend/ directory:
    uv run python scripts/demo_translation.py
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

# Ensure backend/ (parent of scripts/) is importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8")

from core.config import settings  # noqa: E402
from pipeline.agents.translation import translation_agent  # noqa: E402


def _variant(task_id: str, locale: str, personalized: str) -> dict:
    return {
        "task_id": task_id,
        "locale": locale,
        "channel": "email",
        "segment": "consumer",
        "generated_content": personalized,
        "personalized_content": personalized,
        "translated_content": None,
        "final_content": None,
        "status": "personalized",
        "generation_model": "gen-premium",
        "prompt_version": "v1",
        "brand_guide_version": None,
        "translation_engine": None,
        "back_translation_score": None,
        "retry_count": 0,
        "reflexion_applied": False,
        "failure_reason": None,
    }


def _sample_state() -> dict:
    variants = [
        _variant(
            "t-es-clean",
            "es-MX",
            "Get 20% off your first order today. Sign up now.",
        ),
        _variant(
            "t-fr-clean",
            "fr-FR",
            "Our new plan starts at $9.99 per month. Learn more.",
        ),
        _variant(
            "t-de-fail",
            "de-DE",
            # Deliberately open-ended/idiomatic phrasing that a translator is
            # likely to paraphrase heavily -- pushing BLEU/BERTScore away from
            # mBART's more literal reference, to prove the escalation path
            # fires rather than only asserting it in theory.
            "We've got your back, no matter what life throws at you -- "
            "that's the OmniBrand promise, through thick and thin.",
        ),
    ]
    return {
        "campaign_id": "demo-translation-1",
        "org_id": "local-org",
        "brand_id": "local-brand",
        "user_id": "local-user",
        "request_id": "",
        "model_aliases": {},
        "org_config": {},
        "brand_config": {"name": "OmniBrand"},
        "brief": None,
        "variants": variants,
        "errors": [],
        "token_cost_usd": 0.0,
    }


async def main() -> None:
    required = [
        ("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY),
        ("HF_TOKEN", settings.HF_TOKEN),
    ]
    missing = [name for name, val in required if not val]
    if missing:
        print(f"Missing required env var(s): {', '.join(missing)}. Set them in .env and re-run.")
        return

    state = _sample_state()

    print("\n" + "#" * 80)
    print("#  TRANSLATION AGENT - DEMO  (real Claude + real HF Inference Providers)")
    print("#" * 80)
    for v in state["variants"]:
        print(f"\n[{v['task_id']}] locale={v['locale']}")
        print(f"  source (EN): {v['personalized_content']}")

    result = await translation_agent(state)

    print("\n" + "=" * 80)
    for v in state["variants"]:
        print(f"\n[{v['task_id']}]  status={v['status']}  gate={v.get('translation_gate_status')}")
        print(f"  translated : {v.get('translated_content')}")
        print(f"  final      : {v.get('final_content')}")
        print(f"  retries    : {v.get('translation_retry_count')}")
        for check in v.get("translation_checks") or []:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"    [{mark}] {check['name']}: {check['value']:.3f} (>= {check['threshold']})")
        if v.get("translation_content_safety_violations"):
            print(f"    content safety violations: {v['translation_content_safety_violations']}")
        if v.get("failure_reason"):
            print(f"  failure_reason: {v['failure_reason']}")

    print("\n" + "=" * 80)
    print(f"SUMMARY: cost=${result.get('token_cost_usd', 0.0):.4f}")
    if result.get("errors"):
        print("errors (escalated, no human-review path wired yet):")
        for e in result["errors"]:
            print(f"  - {e}")
    print("=" * 80 + "\n")

    print("Full variant state (JSON):")
    print(json.dumps(state["variants"], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
