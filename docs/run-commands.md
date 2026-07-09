# Run Commands

This branch (`feature/base-pipline-quick-eval`) runs the FastAPI + LangGraph pipeline with no external services — no Docker, no Postgres, no Redis, no Qdrant. The graph uses an in-memory checkpointer and is invoked directly in-process.

## Prerequisites

```bash
uv sync --dev
```

That's it — no Docker Compose, no certs, no migrations, no seeding.

## Quick Eval, No Docker

```bash
make run-local
```

Windows: `./scripts/make.ps1 run-local`. Direct command:

```bash
cd backend
uv run uvicorn api.main_local:app --reload --port 8000
```

Or with honcho:

```bash
make dev-local
```

In another terminal:

```bash
curl -X POST http://localhost:8000/campaigns/eval-1/run
```

This returns the full resulting state after the pipeline runs through all stub nodes up to the `review_gate` interrupt. Notes:

- Uses the same `pipeline/graph.py`, `pipeline/state.py`, and `pipeline/agents/*` that a full-stack deployment would use — only the checkpointer and invocation path differ.
- State does not persist across restarts (in-memory checkpointer).
- If you activate a real (non-stub) agent via `traced_llm_call()`, you still need `LITELLM_BASE_URL` reachable — point it at a shared/hosted LiteLLM instance. There is no local LiteLLM container on this branch.

Health check:

```bash
curl http://localhost:8000/health/live
```

## Adding And Testing An Agent

See [quick-eval-branch.md](quick-eval-branch.md) for the step-by-step guide to replacing a stub with a real agent implementation and testing it.

## Running Tests

Run the full pipeline test suite (no external services required):

```bash
make test
```

Direct command:

```bash
cd backend
uv run pytest tests/ -v --timeout=60
```

Run only the fast, non-graph tests:

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k "coroutines or router or write_permissions"
```

Run the graph assembly test (now uses an in-memory `MemorySaver`, no Postgres needed):

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k fan_out_fan_in_accumulation
```

## Current Pipeline Stages

The compiled pipeline currently wires these stages in order:

- `intake_agent`
- `content_generator`
- `personalization_agent`
- `translation_agent`
- `judge_claude`
- `judge_gpt4o`
- `judge_llama`
- `confidence_aggregator`
- `review_gate`
- `publishing_agent`

The graph is configured with `interrupt_before=["review_gate"]`, so execution pauses before `review_gate`.

## Code Quality

```bash
make lint
make format
```
