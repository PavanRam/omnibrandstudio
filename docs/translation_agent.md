# Translation Agent

## Purpose
Fourth node in the pipeline, runs after `personalization_agent` and before
the judge layer. Every variant's source content is always English
(`content_generator` never writes non-English text); for any variant whose
`locale` is a supported non-English locale, this agent translates that ONE
variant's own English content into that ONE locale and runs a hard
pass/fail quality gate. English-locale variants pass straight through.

File: `backend/pipeline/agents/translation.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["translation_agent"]`)
`variants`, `token_cost_usd`, `errors`

Enrichment model: same in-place mutation contract as `personalization_agent`
— never appends to `variants`.

## Supported locales
`{"es", "fr", "de", "hi"}` (base language derived from `variant["locale"]`,
handling both `"es"` and `"es-MX"`-style values). Unsupported locales set
`status="translation_unsupported_locale"` and fail closed (surfaced via
`errors`, no partial output).

## Steps
1. **Source resolution** — `personalized_content` if present, else
   `generated_content`. If neither exists, `status="translation_blocked_no_source"`.
2. **English pass-through** — if the base locale is `"en"`, copies source
   straight into `translated_content`/`final_content`, `status="translated"`,
   `translation_gate_status="skipped_source_locale"`. No LLM call, no cost.
3. **Primary translation** — `traced_llm_call` via the `"translation-primary"`
   model alias (currently pinned to Groq Llama in
   `infra/litellm/litellm_config.yaml`, flagged "switch to Anthropic before
   prod" — never the raw SDK).
4. **Independent reference translation** — `facebook/mbart-large-50-many-to-many-mmt`
   via Hugging Face Inference Providers, computed once per variant
   (doesn't depend on the primary translation output). **Known issue**: this
   model returns errors on HF's free tier — on failure it falls back to the
   same `translation-primary` model, which means the reference is no longer
   an independent model family while that fallback is active.
5. **Back-translation** — locale-dedicated Helsinki-NLP model
   (`opus-mt-{es,fr,de}-en`), or mBART reversed for `hi` (no Helsinki-NLP
   entry exists for Hindi). Falls back to `traced_llm_call` on the primary
   model if the HF call fails outright.
6. **Quality gate** — ALL of must pass, no partial credit:
   - `BLEU >= 25` (via `sacrebleu`)
   - `BERTScore-F1` (per-token embeddings) or `semantic_similarity` (pooled
     cosine, honestly renamed when only pooled vectors are available) `>= 0.84`
   - back-translation cosine similarity to source `>= 0.85`
   - no content-safety violations (toxicity classifier
     `unitary/multilingual-toxic-xlm-roberta`, not yet probe-verified for
     availability/language coverage — degrades to "no violations" on
     failure; plus a brand-name-presence check)
7. **Retry loop** (`MAX_RETRIES = 3`) — failed checks are fed back to the
   model as correction feedback each retry.
8. **Brand rules grounding** — retrieved via the shared RAG retriever
   (`services.rag.get_retriever()`, Chroma or Pinecone per
   `settings.VECTOR_STORE_BACKEND`), queried against the brand guide's source
   locale (`en-US`) regardless of target locale, since brand guides are
   authored once in English. Degrades quietly to `[]` on retrieval failure.
9. **Terminal failure / escalation** — exhausting retries is a hard terminal
   failure: `status="translation_failed"`, `failure_reason` set, an `errors`
   entry, and a best-effort `write_audit()` call
   (`entity_type="translation_gate", action="escalated"`) capturing all
   checks/violations for offline review. `settings.TRANSLATION_HUMAN_ESCALATION_ENABLED`
   is checked but currently only logs intent — this agent has no
   `human_review_requested`/`review_requests` write access, so
   `confidence_aggregator` is the actual safety net today.
10. **Idempotency** — a variant already in a terminal status
    (`translated`, `translation_failed`, `translation_unsupported_locale`,
    `translation_blocked_no_source`) is skipped on checkpoint-resume
    re-invocation, so it's never re-translated/re-billed/re-audited.

## Notable behaviors
- Per-variant exception isolation: one variant's unexpected failure doesn't
  abort processing of sibling variants in the same node invocation.
- Embeddings model: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
  via HF Inference Providers, used both for the semantic check and the
  back-translation cosine check.

## Wrapping
`translation_agent(state)` → `safe_agent_run(_impl, state)`.
