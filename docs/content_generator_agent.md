# Content Generator Agent

## Purpose
Second node in the pipeline (`backend/pipeline/graph.py`), runs after
`intake_agent`. Fans out over every `GenerationTask` produced by intake
(channel × locale × segment) and generates the base English variant for each,
enforcing channel format constraints (char limit, required elements,
prohibited vocabulary) with an in-loop retry-and-correct cycle.

File: `backend/pipeline/agents/content_generator.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["content_generator"]`)
`variants`, `failed_task_ids`, `token_cost_usd`, `current_phase`, `errors`,
`guardrail_flags`

## Steps
1. **Per-task generation** — for each `GenerationTask` in `state["tasks"]`,
   merge `DEFAULT_CHANNEL_CONSTRAINTS[channel]` with the task's own
   `channel_constraints`, pull up to 3 few-shot examples via
   `retrieval.get_examples(brand_id, channel, locale)`, and render the
   channel-specific prompt (`prompts/channel_prompts.py`) with brand tone,
   brief objective/audience/key messages, and brand-guide RAG excerpts
   (`rag_context["brand_guide_chunks"]`, max 3 chunks, 500 chars each).
2. **Model** — `state["model_aliases"]["generation"]`, default `"gen-free"`.
   Always routed through `traced_llm_call` (never a direct SDK/httpx call).
3. **Constraint check + retry loop** (`MAX_RETRIES = 3`) — `_check_constraints`
   validates: char limit (10% tolerance), required elements (`hashtag`,
   `subject_line`, `cta` — each via dedicated regex/keyword heuristics in
   `_has_element`), and prohibited vocabulary (case-insensitive substring
   match). On violation, the failed checks are fed back to the model as
   assistant/user turns and it retries; exhausting retries marks the variant
   `status="failed"` with a `failure_reason` listing the violations.
4. **Output safety guardrail** (flag-only, fail-open) — successfully
   generated content is screened via `safety.screen_output_safety()`; any
   flags are appended to `guardrail_flags` as `"{task_id}:{flag}"`. This never
   blocks the variant — it only annotates state for the judge/aggregator
   layer downstream.
5. **Variant construction** — each result becomes a `ContentVariant`
   (`pipeline/state.py`) with `generated_content` (or `None` if failed),
   `generation_model`, `prompt_version`, `brand_guide_version`, `retry_count`,
   and placeholders (`personalized_content`, `translated_content`,
   `final_content` all `None`) for later agents to enrich in place.
6. **Progress events** — `publish_campaign_event()` fires per-variant
   (`phase="variant_generated"`, 200-char content preview) and once at the
   end (`phase="content_generated"`, counts).
7. **Cost/phase** — accumulates `total_cost` across all tasks/retries into
   `token_cost_usd`; sets `current_phase="content_generated"`.

## Notable behaviors
- `failed_task_ids` collects only tasks that exhausted retries without
  satisfying constraints — these are surfaced but not hard-blocked from the
  rest of the pipeline (a `"failed"` variant is filtered out later by judges
  via `_NON_SCOREABLE_STATUSES`).
- This is also the node `reflexion_router`/`review_router` route back to for
  a single regeneration retry — but on that path, `reflexion.py` mutates the
  variant's content directly rather than re-invoking this node's fan-out
  logic, since only one already-failing variant is being corrected.

## Wrapping
`content_generator(state)` → `safe_agent_run(_impl, state)`, per the
`safe_agent_run` invariant — exceptions never propagate to LangGraph.
