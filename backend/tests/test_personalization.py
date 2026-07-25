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
    resolve_segment_profile,
    scrub_pii,
)
from pipeline.state import merge_variants


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
    content and record every call for assertions.

    The echo is wrapped with a ``Subject:`` line and a CTA so it satisfies the
    email channel's required elements — otherwise the agent's validation loop
    would (correctly) reject it and retry. The persona-specific tone text from
    the prompt is preserved in the middle, so per-persona differentiation and
    PII-redaction assertions still hold."""
    calls: list[dict] = []

    async def fake(model, messages, task, state, **kwargs):
        calls.append({
            "model": model,
            "messages": messages,
            "task": task,
            "agent": kwargs.get("agent"),
        })
        body = messages[-1]["content"]
        content = f"Subject: A note for you\n{body}\nClick here to get started."
        return content, {"cost": 0.001}

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
    assert result == {"token_cost_usd": 0.0}
    assert echo_llm == []


async def test_traced_llm_call_receives_explicit_agent_label(echo_llm):
    variants = [_variant("t-1", "consumer", "Buy our platform.")]
    await personalization_agent(_state(variants))

    assert len(echo_llm) == 1
    assert echo_llm[0]["task"] == "personalization_agent"
    assert echo_llm[0]["agent"] == "personalization_agent"


# ── T4.1 segment resolution (free-text brief label → persona) ──────────────

def test_resolve_exact_persona_name():
    profiles = load_segment_profiles({})
    prof = resolve_segment_profile("High-Income Store Spender", profiles)
    assert "Premium" in prof["tone"]


def test_resolve_by_token_overlap():
    """A free-text segment that shares words with a persona name resolves to
    that persona rather than the generic fallback."""
    profiles = load_segment_profiles({})
    prof = resolve_segment_profile("high income shoppers", profiles)
    assert "Premium" in prof["tone"]  # → High-Income Store Spender


def test_resolve_via_alias_map():
    profiles = load_segment_profiles({})
    prof = resolve_segment_profile(
        "enterprise", profiles, {"enterprise": "High-Income Store Spender"}
    )
    assert "Premium" in prof["tone"]


def test_resolve_unknown_segment_falls_back_without_crashing():
    profiles = load_segment_profiles({})
    prof = resolve_segment_profile("xyzzy no match", profiles)
    # Generic fallback always carries the three keys the prompt builder needs.
    assert {"tone", "reading_level", "cta_style"} <= set(prof)


def test_resolve_partial_org_override_never_raises_keyerror():
    """A segment defined via org_config with only a partial key set is merged
    over the fallback so tone/reading_level/cta_style are always present."""
    profiles = load_segment_profiles(
        {"segment_profiles": {"niche": {"tone": "quirky"}}}
    )
    prof = resolve_segment_profile("niche", profiles)
    assert prof["tone"] == "quirky"
    assert prof["reading_level"] and prof["cta_style"]  # inherited from fallback


# ── T4.3 output validation + retry / fallback ──────────────────────────────

async def test_invalid_output_retries_then_falls_back_to_none(monkeypatch):
    """If the rewrite never satisfies the channel constraints, the agent
    retries MAX_RETRIES+1 times, then sets personalized_content=None and leaves
    status untouched so downstream falls back to generated_content."""
    from pipeline.agents import personalization as perso

    calls: list[dict] = []

    async def bad(model, messages, task, state, **kwargs):
        calls.append({"task": task})
        # Missing subject_line and cta → always violates email constraints.
        return "just some prose with no required elements", {"cost": 0.001}

    monkeypatch.setattr(perso, "traced_llm_call", bad)

    variants = [_variant("t-bad", "High-Income Store Spender", "Buy our platform.")]
    result = await personalization_agent(_state(variants))

    assert len(calls) == perso.MAX_RETRIES + 1          # retried, not one-shot
    assert variants[0]["personalized_content"] is None   # fell back
    assert variants[0]["status"] == "generated"          # status untouched
    assert result["token_cost_usd"] == pytest.approx(0.001 * (perso.MAX_RETRIES + 1))


# ── variants reducer (persistence fix) ─────────────────────────────────────

async def test_agent_returns_enriched_variants_for_persistence(echo_llm):
    """The agent must RETURN the enriched variants (not just mutate in place),
    else the checkpointer drops personalized_content."""
    variants = [_variant("t-hi", "High-Income Store Spender", "Buy our platform.")]
    result = await personalization_agent(_state(variants))
    assert "variants" in result
    assert result["variants"][0]["personalized_content"]
    assert result["variants"][0]["status"] == "personalized"
    # write scope still respected
    assert set(result) <= AGENT_WRITE_PERMISSIONS["personalization_agent"]


def test_merge_variants_upserts_by_task_id():
    existing = [
        {"task_id": "t1", "generated_content": "g1",
         "personalized_content": None, "status": "generated"},
        {"task_id": "t2", "generated_content": "g2",
         "personalized_content": None, "status": "generated"},
    ]
    updates = [{"task_id": "t1", "personalized_content": "p1", "status": "personalized"}]
    merged = merge_variants(existing, updates)
    assert len(merged) == 2  # upsert, not append → no duplication
    t1 = next(v for v in merged if v["task_id"] == "t1")
    assert t1["personalized_content"] == "p1" and t1["status"] == "personalized"
    assert t1["generated_content"] == "g1"  # untouched fields preserved
    t2 = next(v for v in merged if v["task_id"] == "t2")
    assert t2["personalized_content"] is None  # other variant untouched


def test_merge_variants_inserts_and_handles_edges():
    assert merge_variants([], [{"task_id": "t1", "x": 1}]) == [{"task_id": "t1", "x": 1}]
    assert merge_variants(None, None) == []
    # a variant without a task_id is appended, never merged away
    out = merge_variants([{"task_id": "t1"}], [{"no_id": 1}])
    assert len(out) == 2
