# Run Commands

This project currently has two practical execution paths:

- API process via FastAPI.
- Pipeline execution via the worker and Redis queue.

The campaign API routes are still placeholders, so end-to-end pipeline execution currently happens through the worker queue plus the smoke test script, not through an HTTP `POST /campaigns` flow.

## Prerequisites

Run commands from the repository root unless noted otherwise.

If you use `make`:

```bash
make install-dev
make certs
make up
make migrate
make seed
```

If you are on Windows and prefer PowerShell directly:

```powershell
uv sync --dev
mkdir certs -ErrorAction SilentlyContinue
docker compose up -d --wait
cd backend
uv run alembic upgrade head
uv run python ..\scripts\seed_prompts.py
```

For one-shot setup, you can also use:

```bash
make setup
```

## Run The Application

Run the API only:

```bash
make run
```

Direct command:

```bash
cd backend
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Run the worker only:

```bash
make worker
```

Direct command:

```bash
cd backend
uv run python -m worker.main
```

Run API and worker together:

```bash
make dev
```

## Run Just The Pipeline

Today, the pipeline is executed by the worker after a payload is pushed onto the Redis queue `campaigns:queue`.

The smallest real pipeline run is:

1. Start infrastructure.
2. Start the worker.
3. Enqueue a campaign via the smoke script.

Terminal 1:

```bash
make up
make worker
```

Terminal 2:

```bash
make smoke
```

Direct commands:

```bash
docker compose up -d --wait
cd backend
uv run python -m worker.main
```

In a second terminal:

```bash
uv run python scripts/smoke_test.py
```

What this does:

- Pushes a test campaign to Redis.
- Lets the worker build and invoke the LangGraph pipeline.
- Verifies checkpoint history in Postgres.
- Fails if the dead-letter queue is used.

## Run E2E

Current E2E is the smoke path, because the campaign API endpoints are not implemented yet.

Run full smoke E2E:

```bash
make up
make worker
make smoke
```

If you want API and worker running while you smoke test the system:

Terminal 1:

```bash
make run
```

Terminal 2:

```bash
make worker
```

Terminal 3:

```bash
make smoke
```

Note: `scripts/smoke_test.py` bypasses the not-yet-implemented `/campaigns` API and writes directly to the Redis queue.

## Run Different Parts Of The Pipeline

### Pipeline skeleton tests

Run all current pipeline tests:

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v
```

These tests cover:

- Stub coroutine shape.
- Router behavior.
- Per-agent write permissions.
- Basic graph assembly and checkpoint fan-out/fan-in behavior.

### Lightweight pipeline checks

Run only the fast, non-checkpointer tests:

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k "coroutines or router or write_permissions"
```

This is the quickest way to validate pipeline wiring without needing the full worker loop.

### Graph integration check

Run only the graph/checkpointer test:

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k fan_out_fan_in_accumulation
```

This requires the backing services to be available, especially Postgres.

### Full backend test run

Run all backend tests currently present:

```bash
make test
```

Direct command:

```bash
cd backend
uv run pytest tests/ -v --timeout=60
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

The graph is configured with `interrupt_before=["review_gate"]`, so execution pauses before `review_gate` during the current worker-driven flow.

## Useful Support Commands

Bring infrastructure up:

```bash
make up
```

Stop infrastructure:

```bash
make down
```

Tail API and worker logs:

```bash
make logs
```

Check migration history:

```bash
make migrate-history
```