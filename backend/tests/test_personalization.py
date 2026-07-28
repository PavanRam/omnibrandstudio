"""T4 — Personalization agent tests.

Runs fully offline: the LLM call is mocked to echo its prompt back, so we can
assert on the segment conditioning (T4.1/T4.3), PII redaction (T4.2), and the
in-place write contract (T4.4) without a LiteLLM endpoint or content_generator.
"""
import pytest
from pipeline.agents import personalization as perso
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS
from pipeline.agents.personalization import (
    load_segment_profiles,
    personalization_agent,
    scrub_pii,
)


def _variant(task_id: str, segment: str, generated: str) -> dict:
    return {
        "task_id": task_id,
        "locale": "en-US",
        "channel": "email",
        "segment": segment,
        "generated_content": generated,
        "personalized_content": None,
        "translated_content": None,
        "final_content": None,
        "status": "generated",
        "generation_model": None,
        "prompt_version": None,
        "brand_guide_version": None,
        "translation_engine": None,
        "back_translation_score": None,
        "retry_count": 0,
        "reflexion_applied": False,
        "failure_reason": None,
    }


def _state(variants: list[dict]) -> dict:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "org_config": {},
        "brief": None,
        "variants": variants,
        "errors": [],
        "token_cost_usd": 0.0,
    }


@pytest.fixture
def echo_llm(monkeypatch):
    """Mock traced_llm_call: echo the user prompt back as the 'personalized'
    content and record every call for assertions."""
    calls: list[dict] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append({
            "model": model,
            "messages": messages,
            "task": task,
            "agent": kwargs.get("agent"),
        })
        return messages[1]["content"], {"cost": 0.001}

    monkeypatch.setattr(perso, "traced_llm_call", fake)
    return calls


# ── T4.1 segment loading ──────────────────────────────────────────────────

def test_real_personas_loaded_from_brand_guidelines():
    profiles = load_segment_profiles({})
    # The 5 real K-Means personas are loaded from the brand-guideline files.
    assert set(profiles) >= {
        "High-Income Store Spender",
        "Budget-Conscious Low Spender",
        "Web-Savvy Mid-Tier Buyer",
        "Deal-Seeking Value Hunter",
        "Highly Engaged Campaign Responder",
    }
    hi = profiles["High-Income Store Spender"]
    assert "Premium" in hi["tone"]          # voice from tone_voice_per_persona.json
    assert hi["cta_style"]                  # CTA from cta_library.json


def test_org_config_overrides_default_profile():
    profiles = load_segment_profiles(
        {"segment_profiles": {"High-Income Store Spender": {"tone": "custom-tone"}}}
    )
    assert profiles["High-Income Store Spender"]["tone"] == "custom-tone"
    # Non-overridden keys survive the merge.
    assert profiles["High-Income Store Spender"]["cta_style"]


# ── T4.2 PII scan ─────────────────────────────────────────────────────────

def test_scrub_pii_redacts_common_types():
    text = "Contact jane.doe@acme.com or +1 (415) 555-1234; SSN 123-45-6789."
    redacted, found = scrub_pii(text)
    assert "jane.doe@acme.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "EMAIL" in found and "PHONE" in found and "SSN" in found


def test_scrub_pii_handles_empty():
    assert scrub_pii(None) == ("", [])
    assert scrub_pii("") == ("", [])


# ── T4.3 / T4.4 agent behaviour ───────────────────────────────────────────

async def test_two_personas_are_conditioned_differently(echo_llm):
    variants = [
        _variant("t-hi", "High-Income Store Spender", "Buy our platform. Email sales@acme.com."),
        _variant("t-deal", "Deal-Seeking Value Hunter", "Buy our platform. Email sales@acme.com."),
    ]
    result = await personalization_agent(_state(variants))

    hi = next(v for v in variants if v["segment"] == "High-Income Store Spender")
    deal = next(v for v in variants if v["segment"] == "Deal-Seeking Value Hunter")

    # T4.4 — both variants personalized, in place (no duplication).
    assert len(variants) == 2
    assert hi["status"] == "personalized" and deal["status"] == "personalized"
    assert hi["personalized_content"] and deal["personalized_content"]

    # T4.4 — the two personas are conditioned on their real brand voices.
    assert hi["personalized_content"] != deal["personalized_content"]
    assert "Premium" in hi["personalized_content"]      # High-Income voice
    assert "Urgent" in deal["personalized_content"]      # Deal-Seeker voice

    # T4.2 — no raw PII reaches the prompt/output.
    for v in variants:
        assert "sales@acme.com" not in v["personalized_content"]
        assert "[REDACTED_EMAIL]" in v["personalized_content"]

    # Write-permission compliance.
    assert set(result) <= AGENT_WRITE_PERMISSIONS["personalization_agent"]
    assert result["token_cost_usd"] == pytest.approx(0.002)


async def test_skips_variants_without_generated_content(echo_llm):
    variants = [_variant("t1", "sme", None)]  # nothing generated yet
    result = await personalization_agent(_state(variants))
    assert variants[0]["personalized_content"] is None
    assert variants[0]["status"] == "generated"
    assert echo_llm == []  # no LLM call made
    assert result["token_cost_usd"] == 0.0


async def test_empty_variants_is_noop(echo_llm):
    result = await personalization_agent(_state([]))
    assert result == {"token_cost_usd": 0.0, "guardrail_flags": []}
    assert echo_llm == []


async def test_traced_llm_call_receives_explicit_agent_label(echo_llm):
    variants = [_variant("t-1", "consumer", "Buy our platform.")]
    await personalization_agent(_state(variants))

    assert len(echo_llm) == 1
    assert echo_llm[0]["task"] == "personalization_agent"
    assert echo_llm[0]["agent"] == "personalization_agent"
