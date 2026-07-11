# Intake Agent

## Purpose
First node in the pipeline (`backend/pipeline/graph.py`). Turns a raw campaign
brief into a validated `CampaignBrief` and a fan-out `list[GenerationTask]`
that `content_generator` executes against. Pure validation + planning — no
content generation, no LLM call required.

## Write permissions (backend/pipeline/agents/base.py::AGENT_WRITE_PERMISSIONS["intake_agent"])
brief, rag_context, prior_campaigns, brief_valid, brief_validation_errors,
budget_check_passed, tasks, current_phase, token_cost_usd, errors

## Inputs required (not yet wired — prerequisite change)
`backend/api/main_local.py::_initial_state()` currently hardcodes `brief=None`
and `/campaigns/{id}/run` takes no body. Must accept `CreateCampaignRequest`
(already defined in `pipeline/schemas.py`) as the POST body and populate the
initial state's brief-related raw fields from it before `graph.ainvoke()`.

## Steps

1. **Injection screening (fail-closed)**
   - Cheap pattern/keyword check over `raw_text` + `key_messages` for
     instruction-override attempts ("ignore previous instructions",
     "disregard the system prompt", role-override phrasing, etc.)
   - On a hit: do NOT silently strip — set `brief_valid=False` and append to
     `brief_validation_errors`. Fails closed, surfaces to the caller.
   - This is a first-pass triage only, not the full defense — see
     "Safeguards" below for the layered story.

2. **Field validation**
   - `channels`, `locales`, `audience_segments` must be non-empty
     (already `Field(min_length=1)` in `CreateCampaignRequest` — re-validate
     defensively since brief flows through as a plain dict/TypedDict, not the
     Pydantic model, once inside state).
   - `token_budget > 0`.
   - Any failure appends to `brief_validation_errors`, sets `brief_valid=False`.

3. **Build `CampaignBrief`**
   - Map validated request fields 1:1 into the `CampaignBrief` TypedDict
     (`pipeline/state.py`) — objective, target_audience, key_messages,
     tone_override, channels, locales, audience_segments, token_budget,
     raw_text.

4. **Budget check**
   - Deterministic, no LLM call: reject if `token_budget <= 0` or if
     `len(tasks) * ROUGH_TOKENS_PER_TASK > token_budget`.
   - Sets `budget_check_passed`.

5. **RAG context / prior campaigns — explicit no-ops on this branch**
   - `rag_context=None`, `prior_campaigns=[]`.
   - No Qdrant/DB exists on the `intake-agent` quick-eval branch
     (confirmed via `docs/quick-eval-branch.md`) — do not fake retrieval.
     Real implementation belongs on `develop` once Qdrant/DB land.

6. **Task fan-out**
   - Cartesian product of `channels x locales x audience_segments` from the
     validated brief.
   - Each `GenerationTask`: `task_id = f"{locale}_{channel}_{segment}"`,
     plus `channel_constraints: dict` (leave `{}` for now — no channel-rules
     source exists yet on this branch).
   - Only populate `tasks` if `brief_valid and budget_check_passed`;
     otherwise `tasks=[]` so the graph doesn't fan out on bad input.

7. **Phase marker**
   - `current_phase = "intake_complete"`.

8. **Cost**
   - `token_cost_usd = 0.0` (no LLM call in this agent).

## Safeguards — layered, not single-gate
Rules-based pattern matching (step 1) is NOT sufficient alone — it misses
paraphrase, encoding tricks, multi-locale injection, and indirect injection
via retrieved content. Full story:
1. **Structural containment** (applies to every future agent using
   `traced_llm_call`, not just intake): brief/RAG text must always occupy the
   user/data role in `messages`, never the system role — this is the primary
   defense, independent of phrasing.
2. **Intake pattern check** (step 1 above) — cheap early triage.
3. **Judge layer as the real backstop** — `judge_claude`/`judge_gpt4o`/
   `judge_llama` + `critical_violations` + `review_gate` (human-in-the-loop)
   catch anything that slips through generation. Judge criteria should
   explicitly include "instruction-injection artifacts in output."
4. **Least-privilege by architecture** (already enforced) —
   `AGENT_WRITE_PERMISSIONS` + `safe_agent_run` mean even a successful
   injection in one agent can't write outside its authorized state fields or
   crash the graph.

## Implementation shape
New file `backend/pipeline/agents/intake.py`:

```python
async def intake_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        # 1. injection screen -> errors
        # 2. field validation -> brief_valid, brief_validation_errors
        # 3. build CampaignBrief
        # 4. budget check -> budget_check_passed
        # 5. rag_context=None, prior_campaigns=[]
        # 6. build tasks (cartesian product) if valid
        return {
            "brief": brief,
            "brief_valid": brief_valid,
            "brief_validation_errors": errors,
            "budget_check_passed": budget_ok,
            "rag_context": None,
            "prior_campaigns": [],
            "tasks": tasks if (brief_valid and budget_ok) else [],
            "current_phase": "intake_complete",
            "token_cost_usd": 0.0,
        }
    return await safe_agent_run(_impl, state)
```

## Files touched
- `docs/intake_agent.md` — this doc (new)
- `backend/pipeline/agents/intake.py` — real implementation (new)
- `backend/pipeline/graph.py` — swap `intake_agent_stub` import/node for `intake_agent`
- `backend/api/main_local.py` — accept `CreateCampaignRequest` body in `/campaigns/{id}/run`, populate brief in initial state
- `backend/tests/test_pipeline_skeleton.py` — update `node_to_stub`/`AGENT_STUB_NAMES` or add a parallel real-agent test

## Verification
- `make test` (or `uv run pytest backend/tests -v`) — existing write-permission
  and graph-shape tests must still pass with the real agent swapped in
- `uv run uvicorn api.main_local:app --reload --port 8000`, then
  `POST /campaigns/{id}/run` with a `CreateCampaignRequest` body — confirm
  `state.tasks` is populated with the expected cartesian-product task IDs,
  and that an invalid brief (empty channels, bad token_budget, or an
  injection-pattern hit) yields `brief_valid=False` / `tasks=[]` instead of
  proceeding.
