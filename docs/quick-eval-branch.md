# feature/base-pipline-quick-eval — Quick Eval Branch

Purpose: run and evaluate the OmniBrand Studio pipeline (FastAPI + LangGraph + agents) with **zero Docker** — no Postgres, Redis, Qdrant, or worker process. This branch is the bare pipeline core: FastAPI + LangGraph + agents, and nothing else. There is no Docker Compose, no Dockerfile, no auth, no database, no queue on this branch at all.

This branch reuses the real `OmniBrandState`, `pipeline/schemas.py`, and `pipeline/agents/*` from the platform's pipeline contract — the graph runs with an in-memory `MemorySaver` checkpointer and is invoked directly in-process (`graph.ainvoke()`) from `api/main_local.py`, with no queue or worker process in between.

---

## 1. Setup (one time)

```bash
uv sync --dev
```

No `docker compose up`, no `make certs`, no `make migrate`, no `make seed` needed for this path.

## 2. Run the app

```bash
make run-local
```

Windows PowerShell:

```powershell
./scripts/make.ps1 run-local
```

Or with honcho:

```bash
make dev-local
```

Direct command (no make):

```bash
cd backend
uv run uvicorn api.main_local:app --host 0.0.0.0 --port 8000 --reload
```

The server starts on `http://localhost:8000` with an in-memory checkpointer built once at startup (`api/main_local.py`).

## 3. Run a campaign through the pipeline

```bash
curl -X POST http://localhost:8000/campaigns/eval-1/run
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/campaigns/eval-1/run -Method Post
```

This runs the full graph (`intake_agent → content_generator → personalization_agent → translation_agent → judge_claude/judge_gpt4o/judge_llama → confidence_aggregator → review_gate [interrupt] → publishing_agent`) using all-stub agents by default, and returns the resulting `OmniBrandState` as JSON. State does not persist across server restarts.

Health check:

```bash
curl http://localhost:8000/health/live
```

## 4. Adding and testing your own agent

Every agent lives in `backend/pipeline/agents/` and must follow the contract in the root `CLAUDE.md` ("Adding / replacing an agent"). Concretely:

1. **Write the agent function** in a new file, e.g. `backend/pipeline/agents/content_generator.py`:

   ```python
   from pipeline.agents.base import safe_agent_run, traced_llm_call
   from pipeline.state import OmniBrandState

   async def content_generator(state: OmniBrandState) -> dict:
       async def _impl(state: OmniBrandState) -> dict:
           model = state["model_aliases"].get("generation", "gen-free")
           content, usage = await traced_llm_call(
               model=model, messages=[...], task="content_generator", state=state,
           )
           return {
               "variants": [...],           # only fields in AGENT_WRITE_PERMISSIONS["content_generator"]
               "token_cost_usd": usage["cost"],
           }
       return await safe_agent_run(_impl, state)
   ```

   Only return fields listed for that agent name in `AGENT_WRITE_PERMISSIONS` (`backend/pipeline/agents/base.py`).

2. **Wire it into the graph.** In `backend/pipeline/graph.py`, replace the stub import for your node:

   ```python
   from pipeline.agents.content_generator import content_generator
   # from pipeline.agents.stubs import content_generator_stub  # remove or leave for reference
   ...
   g.add_node("content_generator", content_generator)  # was content_generator_stub
   ```

3. **Run it locally, no Docker:**

   ```bash
   make run-local
   curl -X POST http://localhost:8000/campaigns/eval-1/run
   ```

   Inspect the returned `state.variants` (or whichever fields your agent writes) to confirm it worked. Check the terminal running `run-local` for `structlog` output and any `errors` in the response — `safe_agent_run` catches exceptions and reports them there instead of crashing the server.

4. **If your agent calls `traced_llm_call()`** (i.e. it's not a pure-stub test), it needs `LITELLM_BASE_URL` reachable. Point `LITELLM_BASE_URL` in `.env` at a shared/hosted LiteLLM proxy — there is no local LiteLLM container on this branch. `traced_llm_call` on this branch only logs cost/latency via `structlog`; it does not persist cost or audit records anywhere (no Postgres exists here), so per-call cost tracking and audit logging are out of scope for this branch.

5. **Run the unit tests** that check pipeline wiring and write-permission compliance:

   ```bash
   cd backend
   uv run pytest tests/test_pipeline_skeleton.py -v -k "coroutines or router or write_permissions"
   ```

   These don't require any backing service and will catch it if your agent writes an unauthorized state key.

## 5. Multiple developers, multiple agents

Each developer should work on their own agent on their own branch cut from `develop` (e.g. `feature/agent-content-generator`), following the same steps above against the real `graph.py`/`state.py`. This quick-eval branch is a shared reference for **how to run and test locally** — it is not itself a place to land multiple agents' work. Once an agent is implemented and passes tests, open a PR into `develop` from its own feature branch.

## 6. Beyond this branch

This branch intentionally has no persistence, no auth, and no Docker. If a feature needs real checkpoint history, a job queue, or multi-service infrastructure, that work belongs on `develop`, not here.
