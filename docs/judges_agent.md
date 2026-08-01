# Judge Panel Agents (`judges.py`)

## Purpose
Three parallel LLM-as-judge nodes (`judge_claude`, `judge_gpt4o`,
`judge_llama`) fanned out by `judge_gate_router`. Each is an independent,
blind, single-artifact scorer (no pairwise comparison, no cross-visibility
between judges) evaluating every scoreable variant against the retrieved
brand guide. The three differ ONLY by which model alias they read
(`judge-1`/`judge-2`/`judge-3`) — cross-family diversity (Claude/GPT-4o/Llama)
is what gives `confidence_aggregator` its disagreement signal, and lives
entirely in `infra/litellm/litellm_config.yaml` config, not code.

File: `backend/pipeline/agents/judges.py`

## Write permissions
- `AGENT_WRITE_PERMISSIONS["judge_claude"]` = `{"brand_scores", "errors"}`
- `AGENT_WRITE_PERMISSIONS["judge_gpt4o"]` = `{"brand_scores", "errors"}`
- `AGENT_WRITE_PERMISSIONS["judge_llama"]` = `{"brand_scores", "errors"}`

Judges never write `token_cost_usd` — it's a plain (non-fan-in) field, and
three parallel branches writing it in the same LangGraph super-step would be
a concurrent-write error. Cost is recorded separately by `traced_llm_call`
into `campaign_cost_attribution`.

## Steps (shared `_run_judge` helper)
1. Resolve model from `state["model_aliases"][alias_key]`
   (`judge-1`/`judge-2`/`judge-3`), defaulting to the free-tier aliases
   (`DEFAULT_JUDGE_ALIASES` → `judge-1-free`/`judge-2-free`/`judge-3-free`) so
   validation works without paid keys.
2. Build the brand guide excerpt from `rag_context["brand_guide_chunks"]`
   (first 6 chunks joined; `"(no brand guide retrieved)"` if empty).
3. **Skip non-scoreable variants** — any variant with
   `status in {"failed", "translation_failed", "translation_unsupported_locale", "translation_blocked_no_source"}`
   is excluded.
4. **Content resolution** — `final_content` → `translated_content` →
   `personalized_content` → `generated_content` (first non-empty).
5. **Idempotency check** — a judge scores a variant only if it has no score
   yet at the variant's current `retry_count` round
   (`_already_scored(brand_scores, variant_id, model, round_)`), so a
   reflexion re-eval re-scores only the regenerated variant without
   double-counting under `operator.add`.
6. **Judge call** — `build_judge_messages()` (`prompts/judge_prompts.py`) with
   brand guide, channel, locale, content; `traced_llm_call` with
   `response_format={"type": "json_object"}`, `temperature=0`. Latency
   recorded to the `judge_latency` Prometheus histogram, labeled per judge.
7. **Defensive parsing** (`_parse_brand_score`) — tolerates `<thinking>`
   preambles/markdown fences by slicing to the outermost `{...}` before
   `BrandScoreOutput.model_validate()`; returns `None` on any failure so a
   missing/malformed judge response is handled gracefully by the aggregator's
   degraded mode rather than raising.
8. **BrandScore construction** — per-criterion `{score, reasoning, violations,
   citations}` for each criterion in `CRITERIA`, plus `composite_score`,
   `critical_violations`, `routing_decision`, `evaluation_latency_ms`,
   `evaluation_round`.

## Wrapping
Each of `judge_claude`/`judge_gpt4o`/`judge_llama` → `safe_agent_run(_impl, state)`.
