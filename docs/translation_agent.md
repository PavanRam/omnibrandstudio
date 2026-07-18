# Translation Agent

## Purpose
Runs after `personalization_agent`, before the judge layer
(`backend/pipeline/graph.py`). Every variant already carries its own English
source text — `content_generator` always writes English regardless of the
task's locale (see `prompts/channel_prompts.py`; `locale` is only threaded
into the prompt as context, never as a language instruction). So per variant,
this agent's job is: if `variant["locale"]` is a supported non-English
locale, translate that variant's own English content into that ONE locale and
gate the result; otherwise pass it straight through (English) or fail closed
(unsupported locale).

## Write permissions (`backend/pipeline/agents/base.py::AGENT_WRITE_PERMISSIONS["translation_agent"]`)
variants, token_cost_usd, errors

Enrichment model: `variants` is an `operator.add` fan-in field, so this agent
enriches existing variant dicts **in place** (same contract
`personalization_agent` uses) and returns only `token_cost_usd` (+ `errors`
on failure) — it never appends new entries to `variants`.

## Model roles

| Role | Model | Path |
|---|---|---|
| Primary translation | Claude (`translation-primary` alias → `anthropic/claude-sonnet-4-6`) | `traced_llm_call` |
| Independent reference (BLEU / BERTScore-or-semantic_similarity) | `facebook/mbart-large-50-many-to-many-mmt` | HF Inference Providers, direct |
| Back-translation — es / fr / de | `Helsinki-NLP/opus-mt-{lang}-en` | HF Inference Providers, direct |
| Back-translation — hi | mBART, reversed direction | HF Inference Providers, direct |
| Back-translation fallback (any locale, only if the HF call fails) | Claude | `traced_llm_call`, task=`translation_agent_backtranslate_fallback` |
| Embeddings (semantic/cosine checks + brand-rule query) | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | HF Inference Providers, direct |
| Content-safety / toxicity | `unitary/multilingual-toxic-xlm-roberta` | HF Inference Providers, direct — **not yet probe-verified** (availability + per-locale coverage, especially `hi`, unconfirmed) |

HF calls sit outside `traced_llm_call` (not chat-completion shaped) and are
each individually retried via `tenacity`, since they don't get LiteLLM's
router retry policy.

## Steps

1. **Locale scope guardrail** — target locale is always `variant["locale"]`
   (never re-derived from `campaign_brief["locales"]`). Prevents n^2
   translation fan-out.
2. **Source resolution** — `personalized_content` if present, else
   `generated_content` ("two doors": personalization output varies per
   persona/segment and must win when available).
3. **Locale routing**:
   - `en` → passthrough. Zero API calls, zero cost, gate skipped;
     `translated_content`/`final_content` = direct copy of source.
   - `es` / `fr` / `de` / `hi` → full gate (steps 4-8 below).
   - Anything else → fail closed, `status = "translation_unsupported_locale"`.
   - Missing source text (both fields empty) → fail closed,
     `status = "translation_blocked_no_source"`.
4. **Brand-rule retrieval** — a real (not fake) call to Qdrant, filtered by
   `brand_id` + `locale`, wrapped defensively (degrades to `[]` on any
   failure — there's no `brand_rules` collection yet; `content_generator` owns
   real brand-rule application upstream. Kept as a genuine interface so
   ingestion can plug in later with zero structural change).
5. **Independent reference** — mBART translates the *original* English
   source (not Claude's output) into the target locale. Computed once per
   variant, not per retry.
6. **Gate loop** (up to `MAX_RETRIES = 3` attempts):
   - Claude translates the source, brand rules injected as prompt context.
   - Back-translate Claude's output to English (locale-dedicated model, or
     Claude fallback if that HF call fails).
   - Run 3 numeric checks (BLEU ≥ 25, BERTScore-F1-or-semantic_similarity ≥
     0.84, back-translation cosine ≥ 0.85) + 1 boolean content-safety check
     (toxicity classifier + brand-name-preserved check). **All must pass** —
     no partial credit.
   - On failure (and attempts remain): feed Claude the specific failed
     checks + scores as correction feedback, retry.
7. **Terminal outcome**:
   - Pass → `status = "translated"`, `final_content` set, done.
   - Retries exhausted → `status = "translation_failed"`, detailed
     `failure_reason`, **unconditional best-effort** `write_audit()` (wrapped
     so a missing DB connection or non-UUID `org_id`/`brand_id` in
     tests/demos degrades to a logged warning, not a crash), and an entry
     pushed into the `errors` fan-in list — this is the only safety net today
     since there's no human-review path wired (see Safeguards).
8. **Checkpoint-resume guard** — variants already in a terminal status are
   skipped at the top of the loop, so a worker crash/restart doesn't
   re-translate (and re-bill / re-audit) finished work.

## Safeguards — why there's no human review, and what stands in for it

`AGENT_WRITE_PERMISSIONS["translation_agent"]` has no
`human_review_requested`/`review_requests` access — that's exclusively
`confidence_aggregator`'s (still a stub). So a gate failure here cannot force
human review; it also doesn't halt the graph (edges are static, not
per-variant conditional) — the variant still flows on to the judges.

What actually happens instead, layered:
1. **Fail-closed, not silent-pass, on every check.** If mBART's reference
   call fails outright (even after `tenacity` retries), the whole gate fails
   closed — there's no substitute reference, so BLEU/BERTScore can't be
   computed and are never assumed-passing.
2. **Content safety is a separate, non-numeric gate criterion** — a toxicity
   violation blocks the gate even if all 3 numeric checks pass.
3. **Terminal failure is always recorded**: `write_audit()` (best-effort) +
   `errors` entry, even with nobody to route it to yet.
4. **`TRANSLATION_HUMAN_ESCALATION_ENABLED`** (`core/config.py`) is an inert
   placeholder — flipping it only logs intent today; it does nothing
   functionally until `confidence_aggregator` is built to read
   `ContentVariant.translation_gate_status`.
5. **Per-variant isolation** — each variant's translate+gate logic has its
   own try/except inside the loop, separate from the outer `safe_agent_run`,
   so one variant's unexpected crash doesn't abort the remaining siblings in
   the same node invocation.

## Files touched
- `docs/translation_agent.md` — this doc (new)
- `backend/pipeline/agents/translation.py` — real implementation (new)
- `backend/pipeline/graph.py` — swap `translation_agent_stub` import/node for `translation_agent`
- `backend/pipeline/agents/stubs.py` — untouched; `translation_agent_stub` left in place, unused (matches how the other 3 superseded stubs were left orphaned)
- `backend/pipeline/state.py` — `ContentVariant` gains `NotRequired` fields (`translation_retry_count`, `translation_gate_status`, `translation_checks`, `translation_content_safety_violations`) + new `TranslationCheckResult` TypedDict — additive only, no existing literal needed updating
- `backend/pipeline/schemas.py` — Pydantic `TranslationCheckResult` + optional `translation_gate_status` on `VariantSummary`
- `infra/litellm/litellm_config.yaml` — new pinned `translation-primary` alias
- `backend/core/config.py` — `HF_TOKEN`, `TRANSLATION_HUMAN_ESCALATION_ENABLED`
- `pyproject.toml` — `huggingface_hub`, `sacrebleu`, `tenacity` (via `uv add`)
- `backend/tests/test_translation.py` — offline tests (mocked `traced_llm_call` + every HF boundary function)
- `backend/scripts/demo_translation.py` — real Claude + real HF demo, no Docker

## Verification
- `uv run ruff check` — clean on every touched file.
- `uv run pytest backend/tests -v` — 31/32 pass; the 1 failure
  (`test_fan_out_fan_in_accumulation`) needs a live Postgres connection
  (`make up`), unrelated to this agent.
- `uv run python -c "from pipeline.graph import build_graph; build_graph()"`
  — graph constructs with all 12 nodes.
- `uv run python scripts/demo_translation.py` — needs real
  `ANTHROPIC_API_KEY` + `HF_TOKEN` in `.env`; exits cleanly with a clear
  message if either is missing (confirmed in this environment, since neither
  key is set here). **Not yet run against live APIs** — the HF model choices
  (mBART / Helsinki-NLP / the toxicity classifier) and the
  `huggingface_hub` v1.22.0 API surface are unverified against HF Inference
  Providers today; run the demo with real keys to confirm before relying on
  this in production, same as the build brief's own NLLB-before-mBART probe
  discipline.
