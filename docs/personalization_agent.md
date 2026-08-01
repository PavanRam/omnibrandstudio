# Personalization Agent

## Purpose
Third node in the pipeline, runs after `content_generator`. Conditions each
generated variant on its target audience segment (`enterprise` / `sme` /
`consumer`, or org-supplied overrides) — adjusting tone, CTA style, and
reading level for the persona — and writes the result into
`variant["personalized_content"]`.

File: `backend/pipeline/agents/personalization.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["personalization_agent"]`)
`variants`, `token_cost_usd`, `errors`, `guardrail_flags`

Enrichment model: since `variants` is an `operator.add` fan-in field, this
agent cannot replace the list — it mutates the existing variant dicts **in
place** (same accumulation contract `translation_agent` uses downstream) and
returns only `token_cost_usd`/`guardrail_flags`.

## Steps
1. **Segment profile loading** — `load_segment_profiles(org_config)` merges
   org-supplied `segment_profiles` overrides over
   `DEFAULT_SEGMENT_PROFILES`, which is loaded from real brand-guideline data
   files (`data/datasets/processed/brand_guidelines/tone_voice_per_persona.json`
   + `cta_library.json`) if present, else falls back to a small hardcoded
   3-persona table (`_FALLBACK_PROFILES`).
2. **PII scan** (`scrub_pii`) — regex-based redaction (EMAIL, PHONE, SSN,
   CREDIT_CARD patterns) run first over the brief's `raw_text` (logged only,
   not blocking) and then over each variant's source content before it enters
   the personalization prompt. Redacted text — never the raw PII — is what
   gets sent to the model.
3. **Per-variant personalization** — for each variant with
   `generated_content` and not already `status="personalized"`: resolve its
   segment's profile (fallback to a generic profile if segment unknown),
   build a segment-conditioned prompt (`_build_messages` — tone, reading
   level, CTA style, plus the channel's char limit/required elements from
   `DEFAULT_CHANNEL_CONSTRAINTS`), and call
   `state["model_aliases"].get("personalization") or state["model_aliases"]["generation"]`
   (defaults to `gen-free`) via `traced_llm_call`.
4. **In-place enrichment** — sets `variant["personalized_content"]` and
   `variant["status"] = "personalized"`.
5. **Output safety guardrail** (flag-only, fail-open) — same pattern as
   `content_generator`: `safety.screen_output_safety()` on the personalized
   text, flags appended to `guardrail_flags`.
6. **Progress event** — `publish_campaign_event(phase="personalization_complete")`
   with the count personalized.

## Notable behaviors
- No `human_review_requested`/`review_requests` write access — this agent
  cannot itself escalate to human review; any downstream failure surfaces
  only via `token_cost_usd`/logging.
- The persona-profile loader degrades gracefully (empty dict → fallback
  profiles) if the brand-guideline JSON files are missing, so this agent
  never hard-fails on a branch without that data track's output.

## Wrapping
`personalization_agent(state)` → `safe_agent_run(_impl, state)`.
