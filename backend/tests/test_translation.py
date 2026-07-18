"""Translation agent tests.

Runs fully offline: traced_llm_call and every HF-boundary function (mBART,
Helsinki-NLP back-translation, embeddings, content-safety) are monkeypatched,
so we can assert on locale routing, the retry/gate loop, terminal-failure
handling, and the in-place write contract without any live API or infra.

Pure-function checks (cosine, mean-pool, per-token detection, greedy
BERTScore) are tested directly against real math — no mocking needed there.
"""
import pytest
from pipeline.agents import translation as trans
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS
from pipeline.agents.translation import translation_agent


def _variant(task_id: str, locale: str, personalized: str | None, **overrides) -> dict:
    base = {
        "task_id": task_id,
        "locale": locale,
        "channel": "email",
        "segment": "consumer",
        "generated_content": personalized,
        "personalized_content": personalized,
        "translated_content": None,
        "final_content": None,
        "status": "personalized" if personalized else "generated",
        "generation_model": None,
        "prompt_version": None,
        "brand_guide_version": None,
        "translation_engine": None,
        "back_translation_score": None,
        "retry_count": 0,
        "reflexion_applied": False,
        "failure_reason": None,
    }
    base.update(overrides)
    return base


def _state(variants: list[dict], **overrides) -> dict:
    base = {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "brand_id": "brand-1",
        "model_aliases": {},
        "org_config": {},
        "brand_config": {},
        "brief": None,
        "variants": variants,
        "errors": [],
        "token_cost_usd": 0.0,
    }
    base.update(overrides)
    return base


# ── Pure-function checks — real math, no mocking ────────────────────────────


def test_base_locale_normalizes_region_suffix():
    assert trans._base_locale("es-MX") == "es"
    assert trans._base_locale("ES") == "es"
    assert trans._base_locale(None) == ""


def test_cosine_identical_vectors_is_one():
    assert trans._cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero():
    assert trans._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_is_per_token_distinguishes_matrix_from_flat_vector():
    assert trans._is_per_token([[0.1, 0.2], [0.3, 0.4]]) is True
    assert trans._is_per_token([0.1, 0.2, 0.3]) is False


def test_mean_pool_averages_token_vectors():
    pooled = trans._mean_pool([[1.0, 2.0], [3.0, 4.0]])
    assert pooled == pytest.approx([2.0, 3.0])
    # Already-pooled input passes through unchanged.
    assert trans._mean_pool([5.0, 6.0]) == [5.0, 6.0]


def test_greedy_bertscore_f1_identical_sequences_is_one():
    vecs = [[1.0, 0.0], [0.0, 1.0]]
    assert trans._greedy_bertscore_f1(vecs, vecs) == pytest.approx(1.0)


# ── Locale routing / guardrails ──────────────────────────────────────────────


@pytest.fixture
def stub_calls(monkeypatch):
    """Mocks every API-boundary function. Records calls for assertions."""
    calls: dict[str, list] = {
        "claude": [], "mbart": [], "backtranslate": [], "embed": [], "safety": [],
    }

    async def fake_traced_llm_call(model, messages, task, state, **kwargs):
        calls["claude"].append({"task": task, "model": model})
        return "TRANSLATED", {"cost": 0.01}

    async def fake_mbart_translate(text, src_locale, tgt_locale):
        calls["mbart"].append((text, src_locale, tgt_locale))
        return "REFERENCE"

    async def fake_hf_translate_call(text, model):
        calls["backtranslate"].append((text, model))
        return "BACKTRANSLATED"

    async def fake_embed(text):
        calls["embed"].append(text)
        return [1.0, 0.0]

    async def fake_safety(text, locale, state):
        calls["safety"].append(text)
        return []

    monkeypatch.setattr(trans, "traced_llm_call", fake_traced_llm_call)
    monkeypatch.setattr(trans, "_mbart_translate", fake_mbart_translate)
    monkeypatch.setattr(trans, "_hf_translate_call", fake_hf_translate_call)
    monkeypatch.setattr(trans, "_embed", fake_embed)
    monkeypatch.setattr(trans, "_check_content_safety", fake_safety)
    return calls


async def test_english_locale_is_passthrough_with_zero_cost(stub_calls):
    variants = [_variant("t-en", "en-US", "Buy now.")]
    result = await translation_agent(_state(variants))

    assert variants[0]["status"] == "translated"
    assert variants[0]["translation_gate_status"] == "skipped_source_locale"
    assert variants[0]["translated_content"] == "Buy now."
    assert variants[0]["final_content"] == "Buy now."
    assert result["token_cost_usd"] == 0.0
    # No API calls at all for an English-locale variant.
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_unsupported_locale_fails_closed(stub_calls):
    variants = [_variant("t-jp", "ja-JP", "Buy now.")]
    result = await translation_agent(_state(variants))

    assert variants[0]["status"] == "translation_unsupported_locale"
    assert "not in supported set" in variants[0]["failure_reason"]
    assert result["token_cost_usd"] == 0.0
    assert "errors" in result and "t-jp" in result["errors"][0]
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_variant_without_source_content_is_blocked(stub_calls):
    variants = [_variant("t-empty", "es-MX", None)]
    result = await translation_agent(_state(variants))

    assert variants[0]["status"] == "translation_blocked_no_source"
    assert result["token_cost_usd"] == 0.0
    assert "errors" in result
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_terminal_status_variant_is_skipped_on_resume(stub_calls):
    """Checkpoint-resume idempotency: a variant already finished must not be
    re-translated (and re-billed / re-audited) if the node re-runs."""
    variants = [_variant("t-done", "es-MX", "Buy now.", status="translated")]
    result = await translation_agent(_state(variants))

    assert result["token_cost_usd"] == 0.0
    assert "errors" not in result
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_target_locale_is_the_variants_own_locale_never_the_brief(stub_calls):
    """Guards the n^2 explosion: only variant['locale'] is translated into,
    never every locale in campaign_brief['locales']."""
    variants = [_variant("t-fr", "fr-FR", "Buy now.")]
    state = _state(variants, brief={"locales": ["es", "fr", "de", "hi"]})
    await translation_agent(state)

    assert len(stub_calls["mbart"]) == 1
    assert stub_calls["mbart"][0][2] == "fr"  # only translated into fr, not es/de/hi too


# ── Gate orchestration ───────────────────────────────────────────────────────


async def test_gate_passes_on_first_attempt(stub_calls, monkeypatch):
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source):
        return passing_checks

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variants = [_variant("t-es", "es-MX", "Buy now.")]
    result = await translation_agent(_state(variants))

    v = variants[0]
    assert v["status"] == "translated"
    assert v["translation_gate_status"] == "pass"
    assert v["final_content"] == "TRANSLATED"
    assert v["translation_retry_count"] == 0
    assert v["back_translation_score"] == pytest.approx(0.95)
    assert "errors" not in result
    assert len(stub_calls["claude"]) == 1  # no retries needed
    assert stub_calls["claude"][0]["task"] == "translation_agent"
    # mBART reference computed exactly once, not once per retry attempt.
    assert len(stub_calls["mbart"]) == 1

    # Write-permission compliance.
    assert set(result) <= AGENT_WRITE_PERMISSIONS["translation_agent"]


async def test_gate_retries_then_passes(stub_calls, monkeypatch):
    failing = [
        {"name": "bleu", "value": 10.0, "threshold": 25.0, "passed": False},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]
    passing = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]
    attempts = {"n": 0}

    async def fake_run_checks(candidate, reference, back_translation, source):
        attempts["n"] += 1
        return failing if attempts["n"] == 1 else passing

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variants = [_variant("t-fr", "fr-FR", "Buy now.")]
    await translation_agent(_state(variants))

    assert variants[0]["status"] == "translated"
    assert variants[0]["translation_retry_count"] == 1
    assert len(stub_calls["claude"]) == 2  # one retry
    # Reference still computed only once, even though Claude was retried.
    assert len(stub_calls["mbart"]) == 1


async def test_gate_exhausts_retries_and_fails_closed(stub_calls, monkeypatch):
    failing = [
        {"name": "bleu", "value": 10.0, "threshold": 25.0, "passed": False},
        {"name": "semantic_similarity", "value": 0.5, "threshold": 0.84, "passed": False},
        {"name": "back_translation_cosine", "value": 0.5, "threshold": 0.85, "passed": False},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source):
        return failing

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variants = [_variant("t-de", "de-DE", "Buy now.")]
    result = await translation_agent(_state(variants))

    v = variants[0]
    assert v["status"] == "translation_failed"
    assert v["translation_gate_status"] == "fail"
    assert v["translation_retry_count"] == trans.MAX_RETRIES
    assert "checks failed" in v["failure_reason"]
    assert v["final_content"] is None  # never promoted on failure

    # Mandatory (best-effort) error surfacing — no human-review path exists,
    # so this errors entry is the only campaign-level signal of the failure.
    assert "errors" in result
    assert "t-de" in result["errors"][0]

    # MAX_RETRIES + 1 total attempts.
    assert len(stub_calls["claude"]) == trans.MAX_RETRIES + 1


async def test_content_safety_violation_blocks_gate_even_if_metrics_pass(stub_calls, monkeypatch):
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source):
        return passing_checks

    async def fake_safety_violation(text, locale, state):
        return ["brand name 'Acme' missing from translated output"]

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)
    monkeypatch.setattr(trans, "_check_content_safety", fake_safety_violation)

    variants = [_variant("t-safety", "es-MX", "Buy now.")]
    await translation_agent(_state(variants))

    assert variants[0]["status"] == "translation_failed"
    assert "content safety violations" in variants[0]["failure_reason"]


async def test_personalized_content_preferred_over_generated_content(stub_calls, monkeypatch):
    """The 'two doors' contract: personalized_content wins when present."""
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source):
        assert source == "Persona-tailored copy."
        return passing_checks

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variants = [
        _variant(
            "t-both",
            "es-MX",
            personalized="Persona-tailored copy.",
            generated_content="Generic copy.",
        )
    ]
    await translation_agent(_state(variants))
    assert variants[0]["status"] == "translated"


async def test_empty_variants_is_noop(stub_calls):
    result = await translation_agent(_state([]))
    assert result == {"token_cost_usd": 0.0}
    assert all(len(v) == 0 for v in stub_calls.values())
