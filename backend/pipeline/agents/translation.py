"""Translation Agent — brand-aware translation quality gate.

Runs after ``personalization_agent``, before the judge layer. Every variant
already carries its own English source text (``content_generator`` always
writes English regardless of the task's locale — see
``prompts/channel_prompts.py``), so this agent's job per variant is: if
``variant["locale"]`` is a supported non-English locale, translate that
variant's own English content into that ONE locale and gate the result;
otherwise pass it straight through (English) or fail closed (unsupported).

Design (confirmed over prior discussion, not left implicit):
  - Source text: ``personalized_content`` if present, else ``generated_content``
    ("two doors" — personalization output varies per persona/segment and must
    win when available).
  - Target locale is ALWAYS ``variant["locale"]`` — never re-derived from
    ``campaign_brief["locales"]``. This is a hard invariant: looping over all
    campaign locales for every variant would turn n translations into n^2.
  - Primary translation: ``traced_llm_call`` via the "translation-primary"
    model alias (pinned single-provider — never the raw Anthropic/Groq SDK,
    per repo invariant #2).
  - Independent reference (for BLEU / BERTScore-or-semantic_similarity):
    facebook/mbart-large-50-many-to-many-mmt via HF Inference Providers —
    computed once per variant, since it doesn't depend on the primary
    translation's output.
  - Back-translation: locale-dedicated Helsinki-NLP model (es/fr/de), or
    mBART reversed for hi; falls back to the primary model (traced_llm_call)
    if the HF call fails outright.
  - Embeddings: sentence-transformers/paraphrase-multilingual-mpnet-base-v2
    via HF Inference Providers — used for the semantic/cosine checks AND for
    the brand-rule retrieval query embedding.
  - Brand rules: retrieved via the same RAG retriever the rest of the
    pipeline uses (``services.rag.get_retriever()``, backed by Chroma or
    Pinecone per ``settings.VECTOR_STORE_BACKEND``) — not a separate vector
    store. Degrades quietly to ``[]`` on retrieval failure, mirroring
    ``intake_agent_stub``'s pattern.
  - Gate: ALL of {BLEU >= 25, BERTScore-F1-or-semantic_similarity >= 0.84,
    back-translation cosine >= 0.85, no content-safety violations} must pass.
    No partial credit. Up to MAX_RETRIES re-translations on failure, feeding
    the model the specific failed checks as correction feedback. Exhausting
    retries is a hard terminal failure: variant status + failure_reason +
    unconditional (best-effort) write_audit + an `errors` entry — there is no
    human-review path wired today (AGENT_WRITE_PERMISSIONS["translation_agent"]
    has no human_review_requested/review_requests access), so this is the
    actual safety net until confidence_aggregator exists.

Write permissions (AGENT_WRITE_PERMISSIONS["translation_agent"]):
    {"variants", "token_cost_usd", "errors"}

Enrichment model: ``variants`` is an ``operator.add`` fan-in field, so this
agent enriches existing variant dicts **in place** (same contract
``personalization_agent`` uses) and returns only ``token_cost_usd`` — it
never appends new entries to ``variants``.
"""
from __future__ import annotations

import math
from typing import Any, cast

import sacrebleu
import structlog
from core.config import settings
from core.database import get_db
from huggingface_hub import AsyncInferenceClient
from services.rag import get_retriever
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.agents.base import safe_agent_run, traced_llm_call, write_audit
from pipeline.state import ContentVariant, OmniBrandState, TranslationCheckResult

log = structlog.get_logger()

# ── Locale support ──────────────────────────────────────────────────────────
# Base language derived from variant["locale"] (handles both "es" and
# "es-MX"-style values already seen across this codebase's fixtures/brief).
SUPPORTED_LOCALES = {"es", "fr", "de", "hi"}

_MBART_MODEL = "facebook/mbart-large-50-many-to-many-mmt"
_MBART_LANG_CODE = {"en": "en_XX", "es": "es_XX", "fr": "fr_XX", "de": "de_DE", "hi": "hi_IN"}

# Locale -> dedicated back-translation model. "hi" has no Helsinki-NLP entry;
# it uses mBART reversed instead (handled specially in _back_translate).
_BACKTRANSLATION_MODEL: dict[str, str | None] = {
    "es": "Helsinki-NLP/opus-mt-es-en",
    "fr": "Helsinki-NLP/opus-mt-fr-en",
    "de": "Helsinki-NLP/opus-mt-de-en",
    "hi": None,
}

_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

# Not yet probe-verified against HF Inference Providers (availability + exact
# per-locale language coverage, especially "hi", is unconfirmed) — wrapped
# defensively below so an unavailable/unsupported call degrades to "no
# violations found" rather than blocking the gate. Verify with a probe call
# before trusting it in production.
_TOXICITY_MODEL = "unitary/multilingual-toxic-xlm-roberta"
_TOXICITY_THRESHOLD = 0.5

# ── Gate thresholds — config-driven constants, never inline magic numbers ───
MAX_RETRIES = 3
BLEU_THRESHOLD = 25.0
SEMANTIC_THRESHOLD = 0.84
COSINE_THRESHOLD = 0.85

# Terminal statuses — a checkpoint-resume re-invocation must not re-translate
# (and re-bill / re-audit) a variant that already finished.
_TERMINAL_STATUSES = {
    "translated",
    "translation_failed",
    "translation_unsupported_locale",
    "translation_blocked_no_source",
}

_hf_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)

_hf_client_singleton: AsyncInferenceClient | None = None


def _hf_client() -> AsyncInferenceClient:
    global _hf_client_singleton
    if _hf_client_singleton is None:
        _hf_client_singleton = AsyncInferenceClient(
            provider="hf-inference", api_key=settings.HF_TOKEN or None
        )
    return _hf_client_singleton


def _base_locale(locale: str | None) -> str:
    return (locale or "").split("-")[0].strip().lower()


# ── HF calls — outside traced_llm_call (not chat-completion shaped), each
# individually retried since they sit outside LiteLLM's router retry policy ──


@_hf_retry
async def _mbart_translate(text: str, src_locale: str, tgt_locale: str) -> str:
    result = await _hf_client().translation(
        text,
        model=_MBART_MODEL,
        src_lang=_MBART_LANG_CODE[src_locale],
        tgt_lang=_MBART_LANG_CODE[tgt_locale],
    )
    return getattr(result, "translation_text", None) or str(result)


@_hf_retry
async def _hf_translate_call(text: str, model: str) -> str:
    result = await _hf_client().translation(text, model=model)
    return getattr(result, "translation_text", None) or str(result)


@_hf_retry
async def _embed(text: str) -> list[Any]:
    vec = await _hf_client().feature_extraction(text, model=_EMBEDDING_MODEL)
    return vec.tolist() if hasattr(vec, "tolist") else vec


def _is_per_token(vec: Any) -> bool:
    return (
        isinstance(vec, list)
        and len(vec) > 0
        and isinstance(vec[0], list)
        and len(vec[0]) > 0
        and isinstance(vec[0][0], int | float)
    )


def _mean_pool(vec: Any) -> list[float]:
    if not _is_per_token(vec):
        return cast(list[float], vec)
    n = len(vec)
    dim = len(vec[0])
    return [sum(row[i] for row in vec) / n for i in range(dim)]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _greedy_bertscore_f1(cand: list[list[float]], ref: list[list[float]]) -> float:
    """BERTScore's greedy precision/recall matching, reimplemented over
    API-sourced token embeddings (no local model — see module docstring)."""
    sims = [[_cosine(c, r) for r in ref] for c in cand]
    precision = sum(max(row) for row in sims) / len(sims)
    recall = sum(max(col) for col in zip(*sims, strict=False)) / len(ref)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


async def _semantic_check(candidate: str, reference: str) -> TranslationCheckResult:
    cand_vec = await _embed(candidate)
    ref_vec = await _embed(reference)
    if _is_per_token(cand_vec) and _is_per_token(ref_vec):
        value = _greedy_bertscore_f1(cand_vec, ref_vec)
        name = "bertscore_f1"
    else:
        # Only pooled sentence vectors available — name it honestly, don't
        # let an approximation wear the more rigorous metric's name (this
        # would also make it redundant with the back-translation cosine
        # check — same math, different inputs).
        value = _cosine(_mean_pool(cand_vec), _mean_pool(ref_vec))
        name = "semantic_similarity"
    return {
        "name": name,
        "value": value,
        "threshold": SEMANTIC_THRESHOLD,
        "passed": value >= SEMANTIC_THRESHOLD,
    }


async def _back_translate(text: str, locale: str, state: OmniBrandState) -> tuple[str, float]:
    try:
        if locale == "hi":
            translated = await _mbart_translate(text, "hi", "en")
        else:
            model = _BACKTRANSLATION_MODEL[locale]
            assert model is not None
            translated = await _hf_translate_call(text, model)
        return translated, 0.0
    except Exception as exc:
        log.warning(
            "hf_back_translation_failed_using_claude_fallback", locale=locale, error=str(exc)
        )
        model = state["model_aliases"].get("translation", "translation-primary")
        content, usage = await traced_llm_call(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the user's text into English. Return only the translation."
                    ),
                },
                {"role": "user", "content": text},
            ],
            task="translation_agent_backtranslate_fallback",
            state=cast(dict[str, Any], state),
            agent="translation_agent",
        )
        return content, usage.get("cost", 0.0)


# ── Brand rules — retrieved via the pipeline's shared RAG retriever (Chroma
# or Pinecone per settings.VECTOR_STORE_BACKEND), matching intake_agent_stub's
# retrieval pattern. Degrades quietly to [] on any failure — content_generator
# owns the primary brand-rule application; this is supplementary grounding
# for the translation gate specifically.
#
# Queried with the brand guide's SOURCE locale (en-US), not the translation's
# target `locale` — brand guides are authored once in English and apply
# regardless of target language; there is no locale-specific guideline
# content, so filtering by target locale would always return [] for every
# non-English translation. ──────────────────────────────────────────────────

_BRAND_GUIDE_SOURCE_LOCALE = "en-US"


async def _get_brand_rules(state: OmniBrandState, locale: str) -> list[str]:
    try:
        chunks = await get_retriever().retrieve(
            query=f"brand rules for {locale} marketing translation",
            brand_id=state.get("brand_id", ""),
            locale=_BRAND_GUIDE_SOURCE_LOCALE,
            n_results=5,
        )
        return [c.content for c in chunks if c.content]
    except Exception as exc:
        log.warning("brand_rule_retrieval_unavailable", locale=locale, error=str(exc))
        return []


async def _check_content_safety(text: str, locale: str, state: OmniBrandState) -> list[str]:
    violations: list[str] = []

    try:
        result = await _hf_client().text_classification(text, model=_TOXICITY_MODEL)
        for item in result:
            is_dict = isinstance(item, dict)
            label = item.get("label") if is_dict else getattr(item, "label", None)
            score = item.get("score") if is_dict else getattr(item, "score", None)
            if label and score is not None and score >= _TOXICITY_THRESHOLD:
                violations.append(f"{label} ({score:.2f})")
    except Exception as exc:
        log.warning(
            "toxicity_check_unavailable",
            locale=locale,
            error=str(exc),
            note="model availability/language coverage not yet probe-verified",
        )

    brand_name = (state.get("brand_config") or {}).get("name")
    if brand_name and brand_name.lower() not in text.lower():
        violations.append(f"brand name '{brand_name}' missing from translated output")

    return violations


# ── Prompting ────────────────────────────────────────────────────────────────


def _build_translate_messages(
    source: str, locale: str, brand_rules: list[str]
) -> list[dict[str, str]]:
    rules_block = "\n".join(f"- {r}" for r in brand_rules) or "(none available yet)"
    system = (
        "You are a professional marketing translator. Translate the user's "
        "English marketing copy into the target locale, preserving meaning, "
        "tone, and any calls to action or formatting exactly. Never translate "
        "brand or product names. Return only the translated text — no "
        "preamble, no explanation."
    )
    user = (
        f"Target locale: {locale}\nBrand rules to respect:\n{rules_block}\n\n"
        f"Source (English):\n{source}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_retry_feedback(
    checks: list[TranslationCheckResult], safety_violations: list[str]
) -> str:
    lines = ["Your previous translation failed these automated checks:"]
    for c in checks:
        if not c["passed"]:
            lines.append(f"- {c['name']}: {c['value']:.3f} (required >= {c['threshold']})")
    if safety_violations:
        lines.append(f"- content safety: {'; '.join(safety_violations)}")
    lines.append(
        "Revise the translation to address all of the above while preserving "
        "meaning, the brand name, and formatting. Return only the corrected translation."
    )
    return "\n".join(lines)


async def _run_checks(
    candidate: str, reference: str, back_translation: str, source: str
) -> list[TranslationCheckResult]:
    bleu_value = sacrebleu.sentence_bleu(candidate, [reference]).score
    bleu_check: TranslationCheckResult = {
        "name": "bleu",
        "value": bleu_value,
        "threshold": BLEU_THRESHOLD,
        "passed": bleu_value >= BLEU_THRESHOLD,
    }
    semantic_check = await _semantic_check(candidate, reference)

    bt_vec = await _embed(back_translation)
    src_vec = await _embed(source)
    cosine_value = _cosine(_mean_pool(bt_vec), _mean_pool(src_vec))
    cosine_check: TranslationCheckResult = {
        "name": "back_translation_cosine",
        "value": cosine_value,
        "threshold": COSINE_THRESHOLD,
        "passed": cosine_value >= COSINE_THRESHOLD,
    }
    return [bleu_check, semantic_check, cosine_check]


# ── Escalation — best-effort write_audit(); never blocks the terminal outcome
# if the DB isn't initialized (offline tests/demo scripts) or org/brand ids
# aren't real UUIDs (common in test fixtures across this repo). ────────────


async def _escalate(
    variant: ContentVariant,
    state: OmniBrandState,
    source: str,
    reference: str,
    back_translation: str,
    checks: list[TranslationCheckResult],
    safety_violations: list[str],
) -> None:
    try:
        async with get_db() as db:
            await write_audit(
                db,
                entity_type="translation_gate",
                action="escalated",
                brand_id=state.get("brand_id"),
                org_id=state.get("org_id"),
                request_id=state.get("request_id"),
                after_val={
                    "task_id": variant.get("task_id"),
                    "locale": variant.get("locale"),
                    "source_text": source,
                    "claude_translation": variant.get("translated_content"),
                    "reference_translation": reference,
                    "back_translation": back_translation,
                    "checks": checks,
                    "content_safety_violations": safety_violations,
                    "retry_count": variant.get("translation_retry_count"),
                },
            )
            await db.commit()
    except Exception as exc:
        log.error(
            "translation_escalation_audit_failed", task_id=variant.get("task_id"), error=str(exc)
        )

    if settings.TRANSLATION_HUMAN_ESCALATION_ENABLED:
        # Placeholder: translation_agent has no AGENT_WRITE_PERMISSIONS entry
        # for human_review_requested/review_requests, so this flag doesn't
        # yet do anything beyond logging intent. Wired for real once
        # confidence_aggregator reads ContentVariant.translation_gate_status.
        log.info("human_escalation_flagged_but_not_wired", task_id=variant.get("task_id"))


# ── Per-variant orchestration ────────────────────────────────────────────────


async def _run_translation_gate(
    variant: ContentVariant, source: str, locale: str, state: OmniBrandState
) -> tuple[float, str | None]:
    model = state["model_aliases"].get("translation", "translation-primary")
    total_cost = 0.0

    # Independent reference — computed once, doesn't depend on the primary
    # translation's output.
    #
    # KNOWN ISSUE (tracked, not fixed): facebook/mbart-large-50-many-to-many-mmt
    # reports status="error" on HF's free hf-inference tier (confirmed via
    # https://huggingface.co/api/models/facebook/mbart-large-50-many-to-many-mmt
    # ?expand[]=inferenceProviderMapping — not gating/license, not a transient
    # cold-start, the model simply isn't served on the free tier). Without a
    # fallback this call raised for every non-English locale and hard-failed
    # the whole variant via _translate_variant's outer except. Falling back to
    # the primary model here unblocks local/dev E2E runs; it means the BLEU/
    # BERTScore reference is no longer an independent model family for as long
    # as this fallback is active — re-evaluate once mBART is available via a
    # paid Inference Endpoint, a local `transformers` deployment, or a
    # different reference-translation model.
    try:
        reference = await _mbart_translate(source, "en", locale)
    except Exception as exc:
        log.warning("mbart_reference_translation_unavailable", locale=locale, error=str(exc))
        reference, mbart_fallback_cost = await traced_llm_call(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate the user's English text into {locale}. "
                        "Return only the translation."
                    ),
                },
                {"role": "user", "content": source},
            ],
            task="translation_agent_reference_fallback",
            state=cast(dict[str, Any], state),
            agent="translation_agent",
        )
        total_cost += mbart_fallback_cost.get("cost", 0.0)

    brand_rules = await _get_brand_rules(state, locale)
    messages = _build_translate_messages(source, locale, brand_rules)

    translated_text = ""
    back_translation = ""
    checks: list[TranslationCheckResult] = []
    safety_violations: list[str] = []
    retry_count = 0
    gate_passed = False

    for attempt in range(MAX_RETRIES + 1):
        translated_text, usage = await traced_llm_call(
            model=model,
            messages=messages,
            task="translation_agent",
            state=cast(dict[str, Any], state),
            agent="translation_agent",
        )
        total_cost += usage.get("cost", 0.0)

        back_translation, bt_cost = await _back_translate(translated_text, locale, state)
        total_cost += bt_cost

        checks = await _run_checks(translated_text, reference, back_translation, source)
        safety_violations = await _check_content_safety(translated_text, locale, state)
        gate_passed = all(c["passed"] for c in checks) and not safety_violations

        if gate_passed or attempt == MAX_RETRIES:
            break

        retry_count += 1
        log.warning(
            "translation_gate_retry",
            task_id=variant.get("task_id"),
            attempt=attempt,
            checks=checks,
            safety_violations=safety_violations,
        )
        messages = messages + [
            {"role": "assistant", "content": translated_text},
            {"role": "user", "content": _build_retry_feedback(checks, safety_violations)},
        ]

    variant["translated_content"] = translated_text
    variant["translation_engine"] = model
    variant["translation_checks"] = checks
    variant["translation_content_safety_violations"] = safety_violations
    variant["translation_retry_count"] = retry_count
    cosine_check = next((c for c in checks if c["name"] == "back_translation_cosine"), None)
    variant["back_translation_score"] = cosine_check["value"] if cosine_check else None

    if gate_passed:
        variant["final_content"] = translated_text
        variant["status"] = "translated"
        variant["translation_gate_status"] = "pass"
        return total_cost, None

    variant["status"] = "translation_failed"
    variant["translation_gate_status"] = "fail"
    failed_names = [c["name"] for c in checks if not c["passed"]]
    reason = f"translation gate failed after {retry_count} retries: checks failed={failed_names}"
    if safety_violations:
        reason += f"; content safety violations={safety_violations}"
    variant["failure_reason"] = reason
    await _escalate(variant, state, source, reference, back_translation, checks, safety_violations)

    error_msg = f"translation_agent (task_id={variant.get('task_id')}): {reason}"
    return total_cost, error_msg


async def _translate_variant(
    variant: ContentVariant, state: OmniBrandState
) -> tuple[float, str | None]:
    task_id = variant.get("task_id")
    try:
        if variant.get("status") in _TERMINAL_STATUSES:
            return 0.0, None  # checkpoint-resume idempotency guard

        source = variant.get("personalized_content") or variant.get("generated_content")
        locale = _base_locale(variant.get("locale"))

        if not source:
            variant["status"] = "translation_blocked_no_source"
            variant["failure_reason"] = "no personalized_content or generated_content to translate"
            return 0.0, f"translation_agent (task_id={task_id}): {variant['failure_reason']}"

        if locale == "en":
            variant["translated_content"] = source
            variant["final_content"] = source
            variant["status"] = "translated"
            variant["translation_gate_status"] = "skipped_source_locale"
            return 0.0, None

        if locale not in SUPPORTED_LOCALES:
            variant["status"] = "translation_unsupported_locale"
            variant["failure_reason"] = (
                f"locale '{variant.get('locale')}' not in supported set {sorted(SUPPORTED_LOCALES)}"
            )
            return 0.0, f"translation_agent (task_id={task_id}): {variant['failure_reason']}"

        return await _run_translation_gate(variant, source, locale, state)
    except Exception as exc:
        # Per-variant isolation: one variant's unexpected failure must not
        # abort processing for sibling variants in the same node invocation
        # (mutations already applied to earlier variants live on the same
        # shared dict objects, so they survive regardless of this guard —
        # this guard protects the CURRENT variant from a half-written state).
        log.error("translation_variant_failed", task_id=task_id, error=str(exc))
        variant["status"] = "translation_failed"
        variant["failure_reason"] = f"unexpected error: {exc}"
        return 0.0, f"translation_agent (task_id={task_id}): unexpected error: {exc}"


async def translation_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        total_cost = 0.0
        translated = 0
        errors: list[str] = []
        for variant in state.get("variants", []):
            cost, error_msg = await _translate_variant(variant, state)
            total_cost += cost
            if error_msg:
                errors.append(error_msg)
            if variant.get("status") == "translated":
                translated += 1

        log.info(
            "agent_complete",
            agent="translation_agent",
            campaign_id=state.get("campaign_id"),
            translated=translated,
        )
        result: dict[str, Any] = {"token_cost_usd": total_cost}
        if errors:
            result["errors"] = errors
        return result

    return await safe_agent_run(_impl, state)
