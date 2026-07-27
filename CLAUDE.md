# OmniBrand Studio

Multi-tenant agentic content platform. LangGraph pipeline generates brand-compliant content across 6 channels and 2+ locales. FastAPI + PostgreSQL + Redis + ChromaDB + LiteLLM proxy.

---

## Package manager — uv only

```bash
uv sync                   # install / refresh all deps
uv run <cmd>              # run anything in project venv
uv add <pkg>              # add dep (updates pyproject.toml + uv.lock)
```
Never use `pip`, `pip install`, or `poetry`. Always prefix Python commands with `uv run`.

---

## Commands

```bash
make up          # start Docker services (blocks until healthy)
make run         # uv run uvicorn api.main:app --reload  (port 8000)
make worker      # uv run python -m worker.main
make dev         # honcho start (web + worker via Procfile)
make migrate     # uv run alembic upgrade head
make seed        # uv run python scripts/seed_prompts.py
make smoke       # uv run python scripts/smoke_test.py   (acceptance gate)
make test        # uv run pytest tests/ -v
make lint        # ruff check + mypy
make format      # ruff format + ruff check --fix
```

After any schema change: `make migrate` → `make seed` → `make smoke`. Always in that order.

---

## Critical file map

```
backend/
  pipeline/
    state.py          ← OmniBrandState TypedDict — shared contract for all agents
    schemas.py        ← all Pydantic message schemas (BrandScoreOutput, etc.)
    graph.py          ← LangGraph graph, build_graph(), interrupt_before
    agents/
      base.py         ← traced_llm_call · write_audit · safe_agent_run · AGENT_WRITE_PERMISSIONS
      stubs.py        ← 10 stub nodes; replace stubs with real implementations here
  api/
    main.py           ← FastAPI app + lifespan (DB, Redis init)
    deps.py           ← get_current_user · require() · UserContext
    middleware/auth.py← HS256 decode · jti revocation · API key verify
  core/
    config.py         ← Settings singleton (Pydantic BaseSettings)
    database.py       ← asyncpg pool
    redis.py          ← Redis pool singleton
    metrics.py        ← Prometheus CollectorRegistry + all metric definitions
  services/
    prompt_service.py ← PromptService.render() · record_performance()
    audit_service.py  ← write_audit() with PII scrubber
  worker/main.py      ← Redis BLPOP loop → graph.ainvoke()
infra/
  litellm/litellm_config.yaml  ← model aliases + fallback chains
scripts/
  seed_prompts.py     ← seeds prompt_registry + test org/brand
  smoke_test.py       ← end-to-end acceptance gate
```

---

## Invariants — never break

**1. Fan-in fields in OmniBrandState must stay `Annotated[list, <reducer>]`:**
```
brand_scores · aggregated_scores · review_requests
publication_receipts · failed_task_ids · errors   → operator.add

variants → merge_variants (pipeline/state.py) — upserts by task_id instead
of concatenating. Plain operator.add would duplicate an entry whenever a
node (reflexion, personalization, translation, a selective content_generator
regen) re-emits a variant it already produced, which is also the only way
an in-place mutation to a variant survives a checkpoint resume (LangGraph
only persists a channel value a node's return dict actually includes).
Any node touching `variants` must return the touched variant(s) via the
"variants" key — mutating in place and returning `{}` looks correct within
one `ainvoke()` call but silently loses the change on resume.
```

**2. Every LLM call** goes through `traced_llm_call()`. Never call litellm, httpx, or the Anthropic SDK directly in agent code.

**3. Every audit event** goes through `write_audit()`. Never INSERT into `audit_log` directly.

**4. Every agent function body** is wrapped with `safe_agent_run()`. Never let exceptions propagate to LangGraph.

**5. State writes** must only touch fields in `AGENT_WRITE_PERMISSIONS[agent_name]`. Return a partial dict, not the full state.

**6. Model aliases only** — never hardcode `"claude-sonnet-4-6"` or `"gpt-4o"` in agent code. Always read from `state["model_aliases"]`.

**7. Auth is dual-path: JWT (RS256) and API key, both live.** `api/deps.py::get_current_user`
tries a bearer JWT first (`api/middleware/auth.py`, RSA keypair via
`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, `jti` revocation on logout/refresh), then falls
back to `X-API-Key` (`_authenticate_api_key`, hashed lookup against `api_keys`). The frontend
login flow (email/password → access+refresh tokens) uses the JWT path; server-to-server/script
callers (e.g. the Airtable poller) use API keys with narrow scopes. Don't remove either path
without confirming what currently depends on it — this previously said "API key only, JWT
removed," which was wrong; verified 2026-07-26 that JWT is fully live and is what interactive
login actually uses.

---

## Core utility signatures

```python
# base.py — use these everywhere, never bypass them

async def traced_llm_call(
    model: str,           # alias from state["model_aliases"], e.g. "gen-premium"
    messages: list[dict],
    task: str,            # agent name → Langfuse tag + Prometheus label
    state: dict,          # needs campaign_id, org_id, brand_id
    **kwargs,
) -> tuple[str, dict]:    # (content_string, {cost, input_tokens, output_tokens, latency_ms})

async def write_audit(
    db, entity_type: str, action: str, *,
    actor_id=None, entity_id=None, brand_id=None, org_id=None,
    before_val=None, after_val=None, ip_address=None,
) -> None                 # scrubs SENSITIVE_FIELDS before insert

async def safe_agent_run(
    agent_fn: Callable,
    state: OmniBrandState,
    task_id: str | None = None,
) -> dict                 # partial state update; never raises
```

---

## Adding / replacing an agent

1. Implement `async def agent_name(state: OmniBrandState) -> dict` — return only authorised fields
2. Wrap the body: `return await safe_agent_run(_impl, state, task_id)`
3. Wire into `graph.py` — replace the stub import
4. `make smoke` to confirm pipeline still completes end-to-end

Agent function template:
```python
async def my_agent(state: OmniBrandState) -> dict:
    async def _impl(state: OmniBrandState) -> dict:
        model = state["model_aliases"].get("generation", "gen-free")
        content, usage = await traced_llm_call(
            model=model, messages=[...], task="my_agent", state=state
        )
        return {
            "variants": [...],                    # only authorised fields
            "token_cost_usd": usage["cost"],
        }
    return await safe_agent_run(_impl, state)
```

---

## Model aliases (infra/litellm/litellm_config.yaml)

| Alias | Resolves to | Use for |
|---|---|---|
| `gen-premium` | Claude Sonnet | Content generation (brand voice critical) |
| `gen-free` | Llama 70B / Groq | Free-tier generation fallback |
| `judge-1` | Claude Sonnet | Judge 1 — pinned Anthropic family |
| `judge-2` | GPT-4o | Judge 2 — pinned OpenAI family |
| `judge-3` | Llama 70B | Judge 3 — pinned Groq/open-source family |
| `util-fast` | GPT-4o-mini | Classification, extraction, short tasks |
| `eval-model` | Claude Haiku | Prompt critique, evaluation, lightweight LLM tasks |
| `embedding` | text-embedding-3-small | Chroma/Pinecone dense vectors |

---

## Token efficiency — Claude Code behaviour

### Model selection
- **Repo navigation** (reading files, searching, understanding structure): use the lightest tool available — `Read`, `Grep`, `Glob`. These are native tool calls, not LLM calls. No model needed.
- **Small edits** (< 20 lines, single file): inline, no subagent.
- **Complex code generation** (new agent, new service): Sonnet is appropriate — the output quality matters.
- **Prompt critique / eval tasks inside the app**: use `eval-model` alias (Haiku) — not Sonnet.

### Prefer inline over subagents
Spawn a subagent only when **both** conditions are true:
- Tasks are fully independent (different files, no shared state)
- Each task is substantial (≥ 30 lines of new code)

**Always inline (never subagent):**
- File reads and grep
- Single-file edits
- Sequential dependent tasks (migrate → seed → smoke)
- Schema changes (touch state.py + schemas.py + migration in one pass)

**Acceptable to parallelize:**
- Building two independent agents (e.g. `content_generator.py` and `translation.py`) simultaneously since they have different files and no interdependency

### Batch related edits into one response
When a change touches multiple files, do all of them in one pass:

Schema field addition → update in this order, one response:
1. `pipeline/state.py` — add field to TypedDict
2. `pipeline/schemas.py` — update Pydantic model
3. `pipeline/agents/base.py` — update AGENT_WRITE_PERMISSIONS
4. The agent file — use the new field
5. Migration file if the field is persisted

### Read only what you need
Large files (`state.py`, `schemas.py`, `alembic/versions/001_*.py`): read only the relevant section or function, not the whole file. Use line ranges in the Read tool.

### No automated browser testing — ever
Never drive a browser automation tool against this app to test it — no clicking through the UI, no live campaign click-throughs, no "let me verify this in the browser." This is a hard rule with no round limit: it applies on attempt 1 just as much as attempt 5. **The user does all live/UI testing themselves.** For UI/frontend changes, verify via code review, unit/integration tests, or backend checks (curl, psql) that don't require a browser, then tell the user what to check and let them do it.

### Debugging discipline — cap live-verification rounds
A "live test" here means anything that triggers the real paid pipeline (`POST /campaigns/{id}/rerun`, a worker-processed campaign, or any path that calls `traced_llm_call` against real Claude/OpenAI/Gemini) — each pass costs real money (content generation + up to 3 judge calls). This applies to curl/API-driven live tests too, not just browser ones (which are excluded entirely per the rule above).

- **Before ever re-running the live pipeline to check a fix, ask: can this be verified with a mocked/unit test instead?** Almost always yes — `traced_llm_call` and `get_examples` are trivial to monkeypatch. Prove the logic once for free, then confirm live at most once or twice at the end.
- **Cap live-pipeline debugging at 2 rounds.** If the same bug survives 2 live-verification attempts, stop and ask the user how to proceed instead of trying a 3rd time. Don't keep iterating autonomously against paid infra.
- Postgres/Redis inspection (`psql`, checkpoint dumps) is free and fine to use liberally — it's re-triggering the *paid pipeline* that needs a cap, not looking at data.
- If a single session already discovered and fixed 2+ interacting bugs via live re-runs, that's the signal to switch to mocked verification for anything further, not push through with a 3rd/4th/5th live round.

---

## Integration checkpoints

These are the acceptance gates. Run `make smoke` at each:

| Checkpoint | What must work |
|---|---|
| CP1 — after T0+T1 | Brief enters → all stub nodes run → state checkpointed to PostgreSQL |
| CP2 — after T2+T3+T6 | Intake → content generator → variants[] populated with provenance |
| CP3 — after T8+T9 | 3 judges parallel → aggregated score → routing decision → reflexion retry |
| CP4 — after T11+T12 | Approved content publishes to LinkedIn + Email; human review interrupt works |

---

## Do not

- Do not use `asyncio.run()` inside FastAPI routes or agent functions
- Do not import `settings` inside functions — import at module level
- Do not INSERT into `audit_log` directly — use `write_audit()`
- Do not call LiteLLM SDK directly in agents — use `traced_llm_call()`
- Do not use raw model names in agent code — use aliases from `state["model_aliases"]`
- Do not run `alembic` without `uv run` prefix
- Do not use sync SQLAlchemy sessions — always async
- Do not query vector stores without `brand_id` filter — cross-brand data leakage
- Do not commit `.env` — commit `uv.lock`
- Do not spawn subagents for file reads, linting, or single-file edits
