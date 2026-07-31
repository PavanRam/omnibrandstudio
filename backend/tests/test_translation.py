"""Translation agent tests.

Runs fully offline: traced_llm_call and every HF/RAG-boundary function
(Helsinki-NLP reference translation and back-translation, embeddings,
content-safety, brand-rule retrieval) are monkeypatched, so we can assert
on locale routing, the
retry/gate loop, terminal-failure handling, and the in-place write contract
without any live API or infra.

Pure-function checks (cosine, mean-pool, per-token detection, greedy
BERTScore) are tested directly against real math — no mocking needed there.
"""
import pytest
from pipeline.agents import translation as trans
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS
from pipeline.agents.translation import translation_agent
from services.rag.retriever import RetrievedChunk


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


def test_back_translation_reliable_flags_symbol_collapse():
    # Helsinki-NLP opus-mt collapsing to an asterisk run on markdown-heavy
    # input (the live campaign 019fb36e false negative).
    assert trans._back_translation_reliable("* * * * * * * * * *") is False
    assert trans._back_translation_reliable("---- •••• ----") is False
    assert trans._back_translation_reliable("   ") is False
    assert trans._back_translation_reliable("") is False
    # A repetition loop (same token echoed) is equally unusable to embed.
    assert trans._back_translation_reliable("buy buy buy buy buy buy buy buy") is False


def test_back_translation_reliable_accepts_real_english_backtranslation():
    assert (
        trans._back_translation_reliable(
            "Discover our exclusive reserve — limited stock, act now for 20% off."
        )
        is True
    )
    assert trans._back_translation_reliable("Buy now.") is True


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


# ── Brand-rules RAG integration — exercises the real _get_brand_rules against
# a fake retriever, not a mocked-out _get_brand_rules. Confirms the Qdrant ->
# get_retriever() rewrite actually wires the retrieve() call correctly and
# still degrades to [] the same way the rest of the gate expects. ───────────


async def test_get_brand_rules_calls_retriever_with_correct_args(monkeypatch):
    captured: dict = {}

    async def fake_retrieve(*, query, brand_id, locale, n_results):
        captured.update(query=query, brand_id=brand_id, locale=locale, n_results=n_results)
        return [
            RetrievedChunk(
                id="1",
                content="Use formal tone.",
                score=0.9,
                section_type="tone",
                version="v1",
                locale=locale,
            )
        ]

    class FakeRetriever:
        retrieve = staticmethod(fake_retrieve)

    monkeypatch.setattr(trans, "get_retriever", lambda: FakeRetriever())

    rules = await trans._get_brand_rules(_state([]), "es")

    assert rules == ["Use formal tone."]
    assert captured["brand_id"] == "brand-1"
    # Queried with the brand guide's source locale (en-US), never the
    # translation's target locale — brand guides aren't locale-specific.
    assert captured["locale"] == "en-US"
    assert captured["n_results"] == 5


async def test_get_brand_rules_degrades_to_empty_on_retriever_failure(monkeypatch):
    def raising_get_retriever():
        raise RuntimeError("chroma unavailable")

    monkeypatch.setattr(trans, "get_retriever", raising_get_retriever)

    rules = await trans._get_brand_rules(_state([]), "es")

    assert rules == []


# ── Locale routing / guardrails ──────────────────────────────────────────────


@pytest.fixture
def stub_calls(monkeypatch):
    """Mocks every API-boundary function. Records calls for assertions."""
    calls: dict[str, list] = {
        "claude": [], "mbart": [], "reference": [], "backtranslate": [], "embed": [],
        "safety": [], "brand_rules": [],
    }

    async def fake_traced_llm_call(model, messages, task, state, **kwargs):
        calls["claude"].append({"task": task, "model": model, "agent": kwargs.get("agent")})
        return "TRANSLATED", {"cost": 0.01}

    async def fake_mbart_translate(text, src_locale, tgt_locale):
        # Fallback tier only now (2026-07-27, swapped from primary) — this
        # fixture's fake_hf_translate_call succeeds for the reference tier,
        # so mBART is never reached in the default happy-path fixture.
        calls["mbart"].append((text, src_locale, tgt_locale))
        return "REFERENCE"

    async def fake_hf_translate_call(text, model):
        # Helsinki-NLP is now primary for the reference translation
        # (en->locale, _REFERENCE_MODEL) AND still handles back-translation
        # (target->en, _BACKTRANSLATION_MODEL) — same underlying call,
        # routed by which model dict the caller passes.
        if model in trans._REFERENCE_MODEL.values():
            calls["reference"].append((text, model))
            return "REFERENCE"
        calls["backtranslate"].append((text, model))
        return "BACKTRANSLATED"

    async def fake_embed(text):
        calls["embed"].append(text)
        return [1.0, 0.0]

    async def fake_safety(text, locale, state):
        calls["safety"].append(text)
        return []

    async def fake_get_brand_rules(state, locale):
        calls["brand_rules"].append(locale)
        return []

    monkeypatch.setattr(trans, "traced_llm_call", fake_traced_llm_call)
    monkeypatch.setattr(trans, "_mbart_translate", fake_mbart_translate)
    monkeypatch.setattr(trans, "_hf_translate_call", fake_hf_translate_call)
    monkeypatch.setattr(trans, "_embed", fake_embed)
    monkeypatch.setattr(trans, "_check_content_safety", fake_safety)
    monkeypatch.setattr(trans, "_get_brand_rules", fake_get_brand_rules)
    return calls


async def test_english_locale_is_passthrough_with_zero_cost(stub_calls):
    variant = _variant("t-en", "en-US", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert variant["translation_gate_status"] == "skipped_source_locale"
    assert variant["translated_content"] == "Buy now."
    assert variant["final_content"] == "Buy now."
    assert cost == 0.0
    assert error_msg is None
    # No API calls at all for an English-locale variant.
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_unsupported_locale_fails_closed(stub_calls):
    variant = _variant("t-jp", "ja-JP", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translation_unsupported_locale"
    assert "not in supported set" in variant["failure_reason"]
    assert cost == 0.0
    assert error_msg and "t-jp" in error_msg
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_variant_without_source_content_is_blocked(stub_calls):
    variant = _variant("t-empty", "es-MX", None)
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translation_blocked_no_source"
    assert cost == 0.0
    assert error_msg is not None
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_terminal_status_variant_is_skipped_on_resume(stub_calls):
    """Checkpoint-resume idempotency: a variant already finished must not be
    re-translated (and re-billed / re-audited) if the node re-runs."""
    variant = _variant("t-done", "es-MX", "Buy now.", status="translated")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert cost == 0.0
    assert error_msg is None
    assert all(len(v) == 0 for v in stub_calls.values())


# ── Gate orchestration (via _translate_variant directly — fan-out is tested
# separately below, this section only exercises the per-variant gate logic,
# unchanged by the channel x segment fan-out redesign) ──────────────────────


async def test_gate_passes_on_first_attempt(stub_calls, monkeypatch):
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        return passing_checks

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-es", "es-MX", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert variant["translation_gate_status"] == "pass"
    assert variant["final_content"] == "TRANSLATED"
    assert variant["translation_retry_count"] == 0
    assert variant["back_translation_score"] == pytest.approx(0.95)
    assert error_msg is None
    assert len(stub_calls["claude"]) == 1  # no retries needed
    assert stub_calls["claude"][0]["task"] == "translation_agent"
    assert stub_calls["claude"][0]["agent"] == "translation_agent"
    # Reference translation (Helsinki-NLP, primary tier as of 2026-07-27)
    # computed exactly once, not once per retry attempt. mBART never reached.
    assert len(stub_calls["reference"]) == 1
    assert len(stub_calls["mbart"]) == 0


async def test_helsinki_reference_failure_falls_back_to_mbart(stub_calls, monkeypatch):
    """Helsinki-NLP is primary for the reference translation (swapped
    2026-07-27 — see translation.py's _run_translation_gate docstring: BLEU
    was failing live campaigns while semantic/cosine checks both passed,
    traced to mBART's reference translations diverging in phrasing from an
    equally-valid LLM translation). If the Helsinki-NLP call fails, it must
    degrade to mBART (tier 2) rather than jumping straight to the LLM
    validator."""
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def failing_hf_reference(text, model):
        raise RuntimeError("Helsinki-NLP/opus-mt-en-es unavailable on hf-inference free tier")

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        assert reference == "MBART_REFERENCE"  # came from the tier-2 mBART fallback
        return passing_checks

    async def fake_mbart_reference(text, src_locale, tgt_locale):
        return "MBART_REFERENCE"

    monkeypatch.setattr(trans, "_hf_translate_call", failing_hf_reference)
    monkeypatch.setattr(trans, "_mbart_translate", fake_mbart_reference)
    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-helsinki-down", "es-MX", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert error_msg is None
    # No LLM fallback needed — mBART tier absorbed the failure.
    tasks = [c["task"] for c in stub_calls["claude"]]
    assert "translation_agent_reference_fallback" not in tasks


async def test_reference_translation_exhausts_to_validator_model(stub_calls, monkeypatch):
    """Both Helsinki-NLP and mBART fail for the reference translation — must
    degrade to the pooled translation-validator alias as the last resort,
    mirroring _back_translate's existing HF-failure fallback."""
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def failing_mbart_translate(text, src_locale, tgt_locale):
        raise RuntimeError("mbart-large-50 unavailable")

    async def failing_hf_translate_call(text, model):
        if model in trans._REFERENCE_MODEL.values():
            raise RuntimeError("Helsinki-NLP/opus-mt-en-es unavailable on hf-inference free tier")
        return "BACKTRANSLATED"

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        assert reference == "TRANSLATED"  # came from the tier-3 LLM fallback
        assert back_translation == "BACKTRANSLATED"  # unaffected, still the real HF call
        return passing_checks

    monkeypatch.setattr(trans, "_mbart_translate", failing_mbart_translate)
    monkeypatch.setattr(trans, "_hf_translate_call", failing_hf_translate_call)
    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-reference-down", "es-MX", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert error_msg is None
    # Both the fallback reference call and the real translation call hit the
    # primary model — same fake_traced_llm_call, so both are recorded here.
    tasks = [c["task"] for c in stub_calls["claude"]]
    assert "translation_agent_reference_fallback" in tasks
    assert "translation_agent" in tasks
    assert all(c["agent"] == "translation_agent" for c in stub_calls["claude"])


async def test_backtranslate_failure_falls_back_to_primary_model(stub_calls, monkeypatch):
    """Helsinki-NLP back-translation is unavailable. The back-translation call
    must degrade to the primary model instead of hard-failing the variant,
    mirroring the reference-translation fallback above."""
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def failing_hf_translate_call(text, model):
        if model in trans._BACKTRANSLATION_MODEL.values():
            raise RuntimeError("Helsinki-NLP/opus-mt-es-en unavailable on hf-inference free tier")
        return "REFERENCE"

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        assert reference == "REFERENCE"  # unaffected, still the real HF call
        assert back_translation == "TRANSLATED"  # came from the fallback traced_llm_call
        return passing_checks

    monkeypatch.setattr(trans, "_hf_translate_call", failing_hf_translate_call)
    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-backtranslate-down", "es-MX", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert error_msg is None
    tasks = [c["task"] for c in stub_calls["claude"]]
    assert "translation_agent_backtranslate_fallback" in tasks
    assert "translation_agent" in tasks
    assert all(c["agent"] == "translation_agent" for c in stub_calls["claude"])


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

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        attempts["n"] += 1
        return failing if attempts["n"] == 1 else passing

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-fr", "fr-FR", "Buy now.")
    await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert variant["translation_retry_count"] == 1
    assert len(stub_calls["claude"]) == 2  # one retry
    # Reference still computed only once, even though the model call was retried.
    assert len(stub_calls["reference"]) == 1
    assert len(stub_calls["mbart"]) == 0


async def test_gate_exhausts_retries_and_fails_closed(stub_calls, monkeypatch):
    failing = [
        {"name": "bleu", "value": 10.0, "threshold": 25.0, "passed": False},
        {"name": "semantic_similarity", "value": 0.5, "threshold": 0.84, "passed": False},
        {"name": "back_translation_cosine", "value": 0.5, "threshold": 0.85, "passed": False},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        return failing

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant("t-de", "de-DE", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translation_failed"
    assert variant["translation_gate_status"] == "fail"
    assert variant["translation_retry_count"] == trans.MAX_RETRIES
    assert "checks failed" in variant["failure_reason"]
    assert variant["final_content"] is None  # never promoted on failure

    # Mandatory (best-effort) error surfacing — no human-review path exists,
    # so this is the only campaign-level signal of the failure.
    assert error_msg is not None and "t-de" in error_msg

    # MAX_RETRIES + 1 total attempts.
    assert len(stub_calls["claude"]) == trans.MAX_RETRIES + 1


async def test_content_safety_violation_blocks_gate_even_if_metrics_pass(stub_calls, monkeypatch):
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        return passing_checks

    async def fake_safety_violation(text, locale, state):
        return ["brand name 'Acme' missing from translated output"]

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)
    monkeypatch.setattr(trans, "_check_content_safety", fake_safety_violation)

    variant = _variant("t-safety", "es-MX", "Buy now.")
    await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translation_failed"
    assert "content safety violations" in variant["failure_reason"]


async def test_personalized_content_preferred_over_generated_content(stub_calls, monkeypatch):
    """The 'two doors' contract: personalized_content wins when present."""
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]

    async def fake_run_checks(candidate, reference, back_translation, source, reliable=True):
        assert source == "Persona-tailored copy."
        return passing_checks

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    variant = _variant(
        "t-both",
        "es-MX",
        personalized="Persona-tailored copy.",
        generated_content="Generic copy.",
    )
    await trans._translate_variant(variant, _state([variant]))
    assert variant["status"] == "translated"


async def test_backtranslate_degenerate_output_uses_validator_fallback(monkeypatch):
    """Live 019fb36e root cause: HF back-translation returns a successful but
    NMT-collapsed '* * * *' run (not an exception). _back_translate must detect
    the unusable output and fall back to the validator LLM so the cosine check
    runs against real English, and report reliable=True."""

    async def degenerate_hf(text, model):
        return "* * * * * * *"

    async def fake_validator(model, messages, task, state, **kwargs):
        assert task == "translation_agent_backtranslate_fallback"
        return "Real English back-translation.", {"cost": 0.02}

    monkeypatch.setattr(trans, "_hf_translate_call", degenerate_hf)
    monkeypatch.setattr(trans, "traced_llm_call", fake_validator)

    text, cost, reliable = await trans._back_translate("texto de mercadotecnia", "es", _state([]))

    assert text == "Real English back-translation."
    assert reliable is True
    assert cost == pytest.approx(0.02)


async def test_run_checks_non_confident_cosine_is_non_vetoing(monkeypatch):
    """An unusable back-translation yields an inconclusive cosine that must NOT
    veto — the check passes non-blockingly and is flagged confident=False, so
    the gate decides on the two forward metrics alone."""

    async def fake_embed(text):
        return [1.0, 0.0] if text == "src" else [0.0, 1.0]  # orthogonal -> cosine 0.0

    async def fake_semantic(candidate, reference):
        return {
            "name": "semantic_similarity",
            "value": 0.9,
            "threshold": trans.SEMANTIC_THRESHOLD,
            "passed": True,
        }

    monkeypatch.setattr(trans, "_embed", fake_embed)
    monkeypatch.setattr(trans, "_semantic_check", fake_semantic)

    checks = await trans._run_checks(
        "hola", "hola", "garbage", "src", back_translation_reliable=False
    )
    cosine = next(c for c in checks if c["name"] == "back_translation_cosine")
    assert cosine["confident"] is False
    assert cosine["value"] < trans.COSINE_THRESHOLD  # genuinely low
    assert cosine["passed"] is True  # but non-vetoing


async def test_run_checks_confident_low_cosine_still_vetoes(monkeypatch):
    """A CONFIDENT (usable) back-translation with a low cosine is a genuine
    meaning inversion the forward checks may miss — it must still veto."""

    async def fake_embed(text):
        return [1.0, 0.0] if text == "src" else [0.0, 1.0]

    async def fake_semantic(candidate, reference):
        return {
            "name": "semantic_similarity",
            "value": 0.9,
            "threshold": trans.SEMANTIC_THRESHOLD,
            "passed": True,
        }

    monkeypatch.setattr(trans, "_embed", fake_embed)
    monkeypatch.setattr(trans, "_semantic_check", fake_semantic)

    checks = await trans._run_checks(
        "hola", "hola", "a real but semantically wrong sentence", "src",
        back_translation_reliable=True,
    )
    cosine = next(c for c in checks if c["name"] == "back_translation_cosine")
    assert cosine["confident"] is True
    assert cosine["passed"] is False


async def test_non_confident_cosine_tightens_semantic_threshold(monkeypatch):
    """Losing the confirmatory round-trip signal must TIGHTEN, not loosen, the
    gate: a semantic score that would pass at the normal 0.84 bar (0.87) is
    rejected under the stricter 0.90 bar applied when cosine is non-confident."""

    async def fake_embed(text):
        return [1.0, 0.0]

    async def marginal_semantic(candidate, reference):
        return {
            "name": "semantic_similarity",
            "value": 0.87,  # passes 0.84, fails the stricter 0.90
            "threshold": trans.SEMANTIC_THRESHOLD,
            "passed": True,
        }

    monkeypatch.setattr(trans, "_embed", fake_embed)
    monkeypatch.setattr(trans, "_semantic_check", marginal_semantic)

    checks = await trans._run_checks(
        "hola", "hola", "* * * *", "src", back_translation_reliable=False
    )
    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["threshold"] == trans.SEMANTIC_THRESHOLD_NO_CONFIRMATION
    assert semantic["passed"] is False


def _baseline_checks(bleu, semantic, cosine, *, confident=True):
    """Build a checks list as _run_checks would emit it at the informational
    baseline (used to exercise _apply_channel_thresholds in isolation)."""
    return [
        {"name": "bleu", "value": bleu, "threshold": trans.BLEU_THRESHOLD,
         "passed": bleu >= trans.BLEU_THRESHOLD},
        {"name": "semantic_similarity", "value": semantic,
         "threshold": trans.SEMANTIC_THRESHOLD, "passed": semantic >= trans.SEMANTIC_THRESHOLD},
        {"name": "back_translation_cosine", "value": cosine,
         "threshold": trans.COSINE_THRESHOLD, "confident": confident,
         "passed": (not confident) or cosine >= trans.COSINE_THRESHOLD},
    ]


def test_apply_channel_thresholds_relaxes_short_form_social():
    """Regression (campaign 019fb50a): a good transcreative fr social variant
    scored bleu~0.0 / semantic 0.75 / cosine 0.80 — all failing the
    informational baseline. On instagram the relaxed bar must pass all three."""
    checks = _baseline_checks(0.002, 0.75, 0.80)
    assert not all(c["passed"] for c in checks)  # fails at baseline

    trans._apply_channel_thresholds(checks, "instagram")

    assert all(c["passed"] for c in checks)
    bleu = next(c for c in checks if c["name"] == "bleu")
    assert bleu["threshold"] == trans.BLEU_THRESHOLD_SOCIAL


def test_apply_channel_thresholds_noop_for_informational_channel():
    """email/linkedin keep the stricter baseline — the same weak-fidelity
    scores that pass on social must still fail on an informational channel."""
    checks = _baseline_checks(0.002, 0.75, 0.80)
    trans._apply_channel_thresholds(checks, "email")

    assert not all(c["passed"] for c in checks)
    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["threshold"] == trans.SEMANTIC_THRESHOLD


def test_apply_channel_thresholds_still_fails_genuinely_bad_social_translation():
    """The relaxed bar is not a bypass — a translation whose meaning actually
    collapsed (very low semantic + cosine) still fails on social channels."""
    checks = _baseline_checks(0.0, 0.40, 0.45)
    trans._apply_channel_thresholds(checks, "twitter")

    assert not all(c["passed"] for c in checks)


def test_apply_channel_thresholds_preserves_non_confident_tightening_on_social():
    """When _run_checks tightened semantic to the no-confirmation bar (degenerate
    back-translation), the social override maps it to the social no-confirmation
    bar rather than the looser social bar, so a degenerate round-trip can't
    loosen the one remaining meaning check even on social channels."""
    checks = [
        {"name": "bleu", "value": 0.0, "threshold": trans.BLEU_THRESHOLD, "passed": False},
        {"name": "semantic_similarity", "value": 0.74,
         "threshold": trans.SEMANTIC_THRESHOLD_NO_CONFIRMATION, "passed": False},
        {"name": "back_translation_cosine", "value": 0.1,
         "threshold": trans.COSINE_THRESHOLD, "confident": False, "passed": True},
    ]
    trans._apply_channel_thresholds(checks, "instagram")

    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["threshold"] == trans.SEMANTIC_THRESHOLD_SOCIAL_NO_CONFIRMATION
    assert semantic["passed"] is False  # 0.74 < 0.76


def test_reconciliation_rescues_marginal_semantic_when_roundtrip_strong():
    """Regression (campaign 019fb527): es email failed all 3 attempts on
    semantic 0.799-0.814 (< 0.84) while back_translation_cosine held 0.93-0.95.
    A confident round-trip >= the authoritative bar must rescue the semantic
    miss so the informational-channel gate passes."""
    checks = _baseline_checks(33.3, 0.814, 0.953)
    assert not all(c["passed"] for c in checks)  # semantic vetoes at baseline

    trans._apply_backtranslation_reconciliation(checks)

    assert all(c["passed"] for c in checks)
    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["passed"] is True
    assert semantic["reconciled_by"] == "back_translation_cosine"


def test_reconciliation_noop_when_roundtrip_below_authoritative_bar():
    """A merely-passing cosine (>= 0.85 but < 0.90) is not strong enough to
    override the semantic veto — the gate must still fail."""
    checks = _baseline_checks(33.3, 0.814, 0.88)
    trans._apply_backtranslation_reconciliation(checks)

    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["passed"] is False
    assert "reconciled_by" not in semantic


def test_reconciliation_noop_when_roundtrip_not_confident():
    """A degenerate/collapsed back-translation (confident=False) can never
    trigger reconciliation, even if its raw cosine value is numerically high."""
    checks = [
        {"name": "bleu", "value": 33.3, "threshold": trans.BLEU_THRESHOLD, "passed": True},
        {"name": "semantic_similarity", "value": 0.814,
         "threshold": trans.SEMANTIC_THRESHOLD, "passed": False},
        {"name": "back_translation_cosine", "value": 0.95,
         "threshold": trans.COSINE_THRESHOLD, "confident": False, "passed": True},
    ]
    trans._apply_backtranslation_reconciliation(checks)

    semantic = next(c for c in checks if c["name"] == "semantic_similarity")
    assert semantic["passed"] is False
    assert "reconciled_by" not in semantic


def test_reconciliation_does_not_rescue_bleu_or_safety():
    """Reconciliation only touches the semantic meaning check — a failing BLEU
    (lexical) must still veto even when the round-trip is authoritative."""
    checks = _baseline_checks(5.0, 0.814, 0.953)  # bleu below 20 threshold
    trans._apply_backtranslation_reconciliation(checks)

    bleu = next(c for c in checks if c["name"] == "bleu")
    assert bleu["passed"] is False
    assert not all(c["passed"] for c in checks)


async def test_gate_passes_when_backtranslation_unusable_but_forward_metrics_pass(
    stub_calls, monkeypatch
):
    """End-to-end false-negative class from live campaign 019fb36e: even when
    the back-translation is unusable after all fallbacks (reliable=False), a
    translation whose forward metrics pass must NOT be failed by an
    inconclusive cosine."""

    async def unusable_back_translate(text, locale, state):
        return "* * * *", 0.0, False

    async def passing_semantic(candidate, reference):
        return {
            "name": "semantic_similarity",
            "value": 0.95,
            "threshold": trans.SEMANTIC_THRESHOLD,
            "passed": True,
        }

    async def identity_reference(text, model):
        return "TRANSLATED"  # equals the fake primary output -> bleu passes

    monkeypatch.setattr(trans, "_back_translate", unusable_back_translate)
    monkeypatch.setattr(trans, "_semantic_check", passing_semantic)
    monkeypatch.setattr(trans, "_hf_translate_call", identity_reference)

    variant = _variant("t-degenerate", "fr-FR", "Buy now.")
    cost, error_msg = await trans._translate_variant(variant, _state([variant]))

    assert variant["status"] == "translated"
    assert variant["translation_gate_status"] == "pass"
    assert error_msg is None
    cosine = next(
        c for c in variant["translation_checks"] if c["name"] == "back_translation_cosine"
    )
    assert cosine["confident"] is False
    assert cosine["passed"] is True


async def test_empty_variants_is_noop(stub_calls):
    result = await translation_agent(_state([]))
    assert result == {"token_cost_usd": 0.0, "current_phase": "translation_complete"}
    assert all(len(v) == 0 for v in stub_calls.values())


# ── Locale fan-out — translation_agent itself, driven by state["tasks"] +
# campaign_brief["locales"] (2026-07-27 redesign: content_generator no longer
# produces a variant per locale; this agent is the only fan-out point) ──────


def _task(task_id: str, channel: str = "email", segment: str = "consumer") -> dict:
    return {"task_id": task_id, "channel": channel, "segment": segment, "channel_constraints": {}}


async def test_fan_out_creates_one_variant_per_requested_locale(stub_calls, monkeypatch):
    passing_checks = [
        {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
        {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
        {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
    ]
    async def fake_run_checks(*a, **k):
        return passing_checks

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)

    master = _variant("email_consumer", "en-US", "Buy now.")
    state = _state(
        [master],
        tasks=[_task("email_consumer")],
        brief={"locales": ["en-US", "es-MX"]},
    )
    result = await translation_agent(state)

    by_task_id = {v["task_id"]: v for v in result["variants"]}
    assert set(by_task_id) == {"email_consumer", "email_consumer_es"}
    # Source locale: the master itself becomes the deliverable, no real
    # translation call.
    assert by_task_id["email_consumer"]["status"] == "translated"
    assert by_task_id["email_consumer"]["translation_gate_status"] == "skipped_source_locale"
    # Non-source locale: a NEW variant, forked from the master, actually
    # translated.
    assert by_task_id["email_consumer_es"]["locale"] == "es-MX"
    assert by_task_id["email_consumer_es"]["status"] == "translated"
    assert by_task_id["email_consumer_es"]["final_content"] == "TRANSLATED"


async def test_fan_out_always_includes_source_locale_even_if_not_requested(stub_calls, monkeypatch):
    """An English-only campaign still runs through this agent unconditionally
    — no graph-level skip — it just has nothing to translate."""
    master = _variant("sms_consumer", "en-US", "Buy now.")
    state = _state([master], tasks=[_task("sms_consumer", channel="sms")], brief={"locales": []})
    result = await translation_agent(state)

    assert len(result["variants"]) == 1
    assert result["variants"][0]["task_id"] == "sms_consumer"
    assert result["variants"][0]["translation_gate_status"] == "skipped_source_locale"
    assert all(len(v) == 0 for v in stub_calls.values())  # no API calls at all


async def test_fan_out_skips_unsupported_locale(stub_calls, monkeypatch):
    master = _variant("email_consumer", "en-US", "Buy now.")
    state = _state(
        [master], tasks=[_task("email_consumer")], brief={"locales": ["en-US", "ja-JP"]}
    )
    result = await translation_agent(state)

    # Silently dropped — intake_agent already reported this as an error
    # before generation ever started.
    assert {v["task_id"] for v in result["variants"]} == {"email_consumer"}


async def test_fan_out_is_idempotent_on_checkpoint_resume(stub_calls, monkeypatch):
    """A locale variant already marked terminal must not be re-translated
    (and re-billed) if the node re-runs."""
    master = _variant("email_consumer", "en-US", "Buy now.", status="translated")
    already_translated = _variant(
        "email_consumer_es", "es-MX", "Buy now.", status="translated", final_content="Ya hecho."
    )
    state = _state(
        [master, already_translated],
        tasks=[_task("email_consumer")],
        brief={"locales": ["en-US", "es-MX"]},
    )
    result = await translation_agent(state)

    assert result.get("variants", []) == []
    assert result["token_cost_usd"] == 0.0
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_fan_out_respects_reflexion_exclusion_per_locale(stub_calls, monkeypatch):
    """reflexion resets a flagged variant back to status='generated' and
    routes it straight to judges — this must be checked per forked locale
    variant, not just on the master, or a reflexion-touched child would get
    silently re-translated."""
    master = _variant("email_consumer", "en-US", "Buy now.", status="translated")
    reflexion_touched = _variant(
        "email_consumer_es", "es-MX", "Buy now.", status="generated", reflexion_applied=True
    )
    state = _state(
        [master, reflexion_touched],
        tasks=[_task("email_consumer")],
        brief={"locales": ["en-US", "es-MX"]},
    )
    result = await translation_agent(state)

    assert result.get("variants", []) == []
    assert all(len(v) == 0 for v in stub_calls.values())


async def test_write_permission_compliance(stub_calls, monkeypatch):
    async def fake_run_checks(*a, **k):
        return [
            {"name": "bleu", "value": 30.0, "threshold": 25.0, "passed": True},
            {"name": "semantic_similarity", "value": 0.9, "threshold": 0.84, "passed": True},
            {"name": "back_translation_cosine", "value": 0.95, "threshold": 0.85, "passed": True},
        ]

    monkeypatch.setattr(trans, "_run_checks", fake_run_checks)
    master = _variant("email_consumer", "en-US", "Buy now.")
    state = _state([master], tasks=[_task("email_consumer")], brief={"locales": ["en-US", "es-MX"]})
    result = await translation_agent(state)
    assert result["variants"][1]["status"] == "translated"  # sanity: real gate path, not exception
    assert set(result) <= AGENT_WRITE_PERMISSIONS["translation_agent"]
