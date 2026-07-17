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
        calls.append({"model": model, "messages": messages, "task": task})
        return messages[1]["content"], {"cost": 0.001}

    monkeypatch.setattr(perso, "traced_llm_call", fake)
    return calls


# ── T4.1 segment loading ──────────────────────────────────────────────────

def test_default_segment_profiles_present():
    profiles = load_segment_profiles({})
    assert set(profiles) >= {"enterprise", "sme", "consumer"}
    assert profiles["enterprise"]["reading_level"] == "Grade 12"
    assert profiles["consumer"]["reading_level"] == "Grade 8"


def test_org_config_overrides_default_profile():
    profiles = load_segment_profiles(
        {"segment_profiles": {"enterprise": {"tone": "custom-tone"}}}
    )
    assert profiles["enterprise"]["tone"] == "custom-tone"
    # Non-overridden keys survive the merge.
    assert profiles["enterprise"]["reading_level"] == "Grade 12"


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

async def test_enterprise_and_consumer_are_conditioned_differently(echo_llm):
    variants = [
        _variant("t-ent", "enterprise", "Buy our platform. Email sales@acme.com."),
        _variant("t-con", "consumer", "Buy our platform. Email sales@acme.com."),
    ]
    result = await personalization_agent(_state(variants))

    ent = next(v for v in variants if v["segment"] == "enterprise")
    con = next(v for v in variants if v["segment"] == "consumer")

    # T4.4 — both variants personalized, in place (no duplication).
    assert len(variants) == 2
    assert ent["status"] == "personalized" and con["status"] == "personalized"
    assert ent["personalized_content"] and con["personalized_content"]

    # T4.4 — enterprise conditioning differs from consumer.
    assert ent["personalized_content"] != con["personalized_content"]
    assert "Grade 12" in ent["personalized_content"]
    assert "Grade 8" in con["personalized_content"]

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
    assert result == {"token_cost_usd": 0.0}
    assert echo_llm == []
