# Run Commands

> For the full observability walkthrough — Jaeger traces, Grafana dashboards,
> Langfuse LLM traces, Prometheus metrics, and E2E request tracking — see
> **[docs/observability-t0-guide.md](observability-t0-guide.md)**.

> For local-dev mode and `/eval/local-eval` command matrices (Bash + PowerShell), see
> **[docs/local-eval-developer-guide.md](local-eval-developer-guide.md)**.

This project has two execution paths:

- **API process** — FastAPI on port 8000. `POST /campaigns` is implemented and
  enqueues a campaign to Redis, returning a UUIDv7 `campaign_id`.
- **Worker process** — BLPOP consumer that drives the LangGraph pipeline.
  The app always exposes its own Prometheus metrics; OTel export to Jaeger is
  enabled by the full Compose profile.

`make up` starts the lightweight application stack: Postgres, Redis, LiteLLM,
MailHog, API, and worker. Use `make up-full` when you also need Langfuse,
Prometheus, Grafana, Jaeger, exporters, and MinIO.

## Re-index After The Embedding Change

Hosted embeddings use the versioned collection suffix
`litellm_v1_384`. Existing local Chroma collections are intentionally left
untouched, so old local-model vectors cannot mix with the new embedding space.
Re-ingest retained guides through the upload API, or reload the bundled seed
data:

```bash
cd backend
uv run python scripts/ingest_seed_datasets.py \
  --seed-dir data/datasets/processed \
  --org-id 00000000-0000-0000-0000-000000000001 \
  --brand-id 00000000-0000-0000-0000-000000000002 \
  --locale en-US \
  --version litellm-v1
```

Configure `OPENAI_API_KEY` (or repoint LiteLLM's `embedding` alias to another
embedding provider) before re-ingesting. Otherwise the operation succeeds in
explicit degraded hash mode and does not provide semantic retrieval. Pinecone
users must ensure their target index accepts 384-dimensional vectors.

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

## Run E2E — via HTTP API (recommended)

`POST /campaigns` is now implemented. This path gives full request-ID
propagation and produces Jaeger traces.

Terminal 1 — full infrastructure (required for the Jaeger links below):

```bash
make up-full
```

Terminal 2 — worker (Prometheus metrics on :9091, OTel to Jaeger):

```bash
make worker
```

Terminal 3 — API (OTel to Jaeger, metrics on :8000/metrics):

```bash
make run
```

Terminal 4 — send a request:

```bash
curl -s -X POST http://localhost:8000/campaigns \
  -H "Content-Type: application/json" \
  -d '{
    "brand_id": "00000000-0000-0000-0000-000000000002",
    "objective": "Launch sustainability report",
    "target_audience": "ESG investors",
    "key_messages": ["Net zero by 2030"],
    "channels": ["linkedin"],
    "locales": ["en-US"],
    "audience_segments": ["enterprise"],
    "token_budget": 4000
  }' | python -m json.tool
```

Then open:
- http://localhost:16686 — Jaeger traces for this request
- http://localhost:9090 — Prometheus metrics
- http://localhost:3000 — Grafana dashboards (Campaign Operations)

## Run E2E — structured validation (smoke test)

The default smoke gate inserts a valid campaign row, enqueues its worker task,
and waits for a persisted `published` or `awaiting_review` status. It checks
only services in the lightweight stack:

```bash
make smoke
# or with custom parameters:
uv run python scripts/smoke_test.py --lite --count 3 --wait-secs 300
```

Use `make smoke-full` to additionally require Prometheus, Grafana, Jaeger,
scrape targets, alert rules, and post-run metric series. Add
`--require-publishing` for a strict CP4 run that must reach `published` and
appear in MailHog; an ordinary run may legitimately pause for human review.

## Run E2E — queue bypass (pipeline-only)

If you want to test just the pipeline without the API:

Terminal 1:

```bash
make up
make worker
```

Terminal 2 (push directly to Redis):

```bash
python - <<'EOF'
import json, redis
r = redis.from_url("redis://localhost:6379")
r.lpush("campaigns:queue", json.dumps({
    "campaign_id": "01900000-0000-7000-8000-000000000001",
    "org_id":      "00000000-0000-0000-0000-000000000001",
    "brand_id":    "00000000-0000-0000-0000-000000000002",
    "user_id":     "test",
    "request_id":  "01900000-0000-7000-8000-000000000099",
}))
print("enqueued")
EOF
```



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

## RAG Local Start and Ingestion

Use this section when starting a fresh instance and you want RAG ready before campaign requests.

### Chroma (local default)

#### Backend config

- `VECTOR_STORE_BACKEND=chroma`
- `CHROMA_PERSIST_PATH=/app/data/chroma` (Docker local default)

#### Start RAG locally

Terminal 1 - infrastructure:

```bash
make up
```

Terminal 2 - API:

```bash
make run
```

Optional Terminal 3 - worker:

```bash
make worker
```

Optional health checks:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/health/ready
```

#### Ingest via API (runtime, one guide at a time)

Endpoint:

- `POST /knowledge/brand-guides`

Bash:

```bash
curl -X POST http://localhost:8000/knowledge/brand-guides \
  -F brand_id=00000000-0000-0000-0000-000000000002 \
  -F locale=en-US \
  -F version=v1 \
  -F guide_file=@./docs/sample-brand-guide.md
```

PowerShell:

```powershell
curl.exe -X POST http://localhost:8000/knowledge/brand-guides `
  -F "brand_id=00000000-0000-0000-0000-000000000002" `
  -F "locale=en-US" `
  -F "version=v1" `
  -F "guide_file=@docs/sample-brand-guide.md"
```

Verify:

```bash
curl "http://localhost:8000/knowledge/brand-guides/00000000-0000-0000-0000-000000000002"
curl "http://localhost:8000/knowledge/brand-guides/00000000-0000-0000-0000-000000000002?include_inactive=true"
```

#### Ingest via script (bootstrap/bulk)

Script:

- `backend/scripts/ingest_seed_datasets.py`

Expected seed directory layout:

- `brand_guidelines/*.json`
- `customer_segments.csv`
- `campaigns_clean.csv`
- `social_media_ads_clean.csv`
- `sentiment140_clean.csv`

Bash:

```bash
cd backend
uv run python scripts/ingest_seed_datasets.py \
  --seed-dir ../data/rag-seed \
  --brand-id 00000000-0000-0000-0000-000000000002 \
  --locale en-US \
  --version seed-v1
```

PowerShell:

```powershell
cd backend
uv run python scripts/ingest_seed_datasets.py `
  --seed-dir ..\data\rag-seed `
  --brand-id 00000000-0000-0000-0000-000000000002 `
  --locale en-US `
  --version seed-v1
```

Optional copy-from:

```bash
cd backend
uv run python scripts/ingest_seed_datasets.py \
  --seed-dir ../data/rag-seed \
  --copy-from /path/to/source-seed \
  --brand-id 00000000-0000-0000-0000-000000000002 \
  --locale en-US \
  --version seed-v1
```

### Pinecone (managed external vector store)

Use this mode when you want managed vector infrastructure instead of local Chroma persistence.

#### Backend config

Set all of:

- `VECTOR_STORE_BACKEND=pinecone`
- `PINECONE_API_KEY=<key>`
- `PINECONE_ENVIRONMENT=<environment>`
- `PINECONE_INDEX=<index-name>`

Example (Bash):

```bash
export VECTOR_STORE_BACKEND=pinecone
export PINECONE_API_KEY=<key>
export PINECONE_ENVIRONMENT=<environment>
export PINECONE_INDEX=<index-name>
```

Example (PowerShell):

```powershell
$env:VECTOR_STORE_BACKEND = "pinecone"
$env:PINECONE_API_KEY = "<key>"
$env:PINECONE_ENVIRONMENT = "<environment>"
$env:PINECONE_INDEX = "<index-name>"
```

#### Start with Pinecone backend

1. Restart API and worker after setting env vars.
2. Re-run ingestion for the selected Pinecone index.

Startup commands are the same:

```bash
make up
make run
# optional
make worker
```

#### Ingest via API and script

Use the same API and script commands from the Chroma section.

Important: switching backend does not migrate vectors automatically; always re-index after a backend change.

### Recommended sequence (either backend)

1. Start infra and run DB migration.
2. Start API.
3. Run script-based ingest for baseline corpora (guidelines, segments, campaigns, sentiment).
4. Run API-based ingest for latest brand guide override/version.
5. Verify `/knowledge/brand-guides/{brand_id}` shows expected active version.
6. Start worker and run a campaign smoke flow.

### Notes

- API-based ingest is the canonical runtime operational path.
- Script-based ingest is intended for bootstrap, migration import, and non-interactive bulk setup.
- If seed files are missing, script skips that dataset type and continues.

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
