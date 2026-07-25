# Run & Operations Guide

> **First-time setup?** See **[docs/setup.md](setup.md)** for prerequisites, environment configuration, infrastructure startup, and the one-time setup sequence.

> For local-dev eval mode and `/eval/local-eval` command matrices (Bash + PowerShell), see **[docs/local-eval-developer-guide.md](local-eval-developer-guide.md)**.

This guide covers day-to-day run paths, pipeline execution, RAG ingestion, and testing.

---

## Table of Contents

1. [Run The Full Application](#1-run-the-full-application)
2. [E2E Run Paths](#2-e2e-run-paths)
3. [Pipeline Stages](#3-pipeline-stages)
4. [RAG Ingestion](#4-rag-ingestion)
5. [Testing](#5-testing)

---

## 1. Run The Full Application

The application has two processes — run each in its own terminal from the repo root:

**Terminal 1 — API (FastAPI on :8000):**

```bash
make run
# or direct:
cd backend && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Worker (LangGraph pipeline consumer):**

```bash
make worker
# or direct:
cd backend && uv run python -m worker.main
```

**Or both together with honcho:**

```bash
make dev
```

---

## 2. E2E Run Paths

### Via HTTP API (recommended)

`POST /campaigns` enqueues a campaign and returns a UUIDv7 `campaign_id`. This path gives full request-ID propagation and Jaeger traces.

Terminal 1 — infrastructure:

```bash
make up
```

Terminal 2 — worker (Prometheus metrics on :9091, OTel to Jaeger):

```bash
make worker
```

Terminal 3 — API (OTel to Jaeger, metrics on :8000/metrics):

```bash
make run
```

Terminal 4 — send a campaign request:

```bash
curl -s -X POST http://localhost:8000/campaigns \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-local-chat-key" \
  -d '{
    "brand_id": "00000000-0000-0000-0000-000000000002",
    "objective": "Launch sustainability report",
    "target_audience": "ESG investors",
    "key_messages": ["Net zero by 2030"],
    "channels": ["linkedin", "email"],
    "locales": ["en-US"],
    "audience_segments": ["enterprise"],
    "token_budget": 4000
  }' | python -m json.tool
```

Then open:
- http://localhost:16686 — Jaeger traces for this request
- http://localhost:9090 — Prometheus metrics
- http://localhost:3000 — Grafana dashboards (Campaign Operations)
- http://localhost:8025 — MailHog (demo email output)

### Via Smoke Test (structured validation)

Sends 20 dummy campaigns through the queue, then verifies all observability signals are present:

```bash
make smoke
# or with custom parameters:
uv run python scripts/smoke_test.py --count 20 --wait-secs 60
```

The script checks: API health, Prometheus targets UP, alert rules loaded, Grafana dashboards provisioned, Jaeger reachable, campaign processing, and metric series populated.

### Via Queue Bypass (pipeline-only, no API)

If you want to test the pipeline without the API layer:

Terminal 1:

```bash
make up && make worker
```

Terminal 2 — push directly to Redis:

```python
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

---

## 3. Pipeline Stages

The compiled LangGraph pipeline wires these stages in order:

```
intake_agent
  → content_generator
  → personalization_agent
  → translation_agent
  → judge_gate                    ← decides panel size (full / lite / skip)
  → judge_claude ┐
  → judge_gpt4o  ├── (parallel fan-out)
  → judge_llama  ┘
  → confidence_aggregator
  → reflexion                     ← self-correction retry for failing variants
  → review_gate                   ← interrupt point (human review)
  → publishing_agent              → MailHog email delivery
  → END
```

All agents are real implementations (no stubs in the default pipeline).

The graph is compiled with `interrupt_before_review_gate=True` by default. When the pipeline reaches `review_gate`, `graph.ainvoke()` pauses and the worker sets `campaign.status = "awaiting_review"`. A human reviewer then approves/rejects via `POST /reviews/{id}/decide`, which resumes the graph from the saved LangGraph checkpoint through to `publishing_agent`.

For the human review testing guide, see [`docs/review-gate-testing-guide.html`](review-gate-testing-guide.html).

---

## 4. RAG Ingestion

Use this section when starting a fresh instance and you want RAG context ready before campaign requests.

### Chroma (local default)

**Config:** `VECTOR_STORE_BACKEND=chroma` (default, no external account needed)

#### Ingest via API (runtime, one guide at a time)

```bash
curl -X POST http://localhost:8000/knowledge/brand-guides \
  -H "X-API-Key: dev-local-chat-key" \
  -F brand_id=00000000-0000-0000-0000-000000000002 \
  -F locale=en-US \
  -F version=v1 \
  -F guide_file=@/path/to/your-brand-guide.md
```

PowerShell:

```powershell
curl.exe -X POST http://localhost:8000/knowledge/brand-guides `
  -H "X-API-Key: dev-local-chat-key" `
  -F "brand_id=00000000-0000-0000-0000-000000000002" `
  -F "locale=en-US" `
  -F "version=v1" `
  -F "guide_file=@C:\path\to\your-brand-guide.md"
```

> `guide_file` accepts any Markdown/text brand guide you have on hand — there is no bundled sample file in this repo. Point it at a real brand guidelines document.

Verify ingestion:

```bash
curl "http://localhost:8000/knowledge/brand-guides/00000000-0000-0000-0000-000000000002"
```

#### Ingest via script (bootstrap / bulk)

Script: `backend/scripts/ingest_seed_datasets.py`

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

### Pinecone (managed external vector store)

Use this mode when you want managed vector infrastructure instead of local Chroma persistence.

**Config** — set all of:

```bash
export VECTOR_STORE_BACKEND=pinecone
export PINECONE_API_KEY=<key>
export PINECONE_ENVIRONMENT=<environment>
export PINECONE_INDEX=<index-name>
```

PowerShell:

```powershell
$env:VECTOR_STORE_BACKEND = "pinecone"
$env:PINECONE_API_KEY = "<key>"
$env:PINECONE_ENVIRONMENT = "<environment>"
$env:PINECONE_INDEX = "<index-name>"
```

Restart API and worker after setting env vars, then re-run ingestion. Switching backends does **not** migrate vectors automatically — always re-index after a backend change.

### Recommended ingestion sequence (either backend)

1. Start infra and run DB migration: `make up && make migrate`
2. Start API: `make run`
3. Run script-based ingest for baseline corpora (guidelines, segments, campaigns, sentiment)
4. Run API-based ingest for latest brand guide override/version
5. Verify: `curl http://localhost:8000/knowledge/brand-guides/{brand_id}`
6. Start worker and run a campaign smoke flow: `make worker && make smoke`

> **API-based ingest** is the canonical runtime operational path.  
> **Script-based ingest** is intended for bootstrap, migration import, and non-interactive bulk setup.  
> If seed files are missing, the script skips that dataset type and continues.

---

## 5. Testing

### Full backend test run

```bash
make test
# or direct:
cd backend && uv run pytest tests/ -v --timeout=60
```

### Pipeline skeleton tests

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v
```

These tests cover: stub coroutine shape, router behaviour, per-agent write permissions, and graph assembly/checkpoint fan-out/fan-in.

### Lightweight pipeline checks (fast, no checkpointer)

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k "coroutines or router or write_permissions"
```

### Graph integration check (requires Postgres)

```bash
cd backend
uv run pytest tests/test_pipeline_skeleton.py -v -k fan_out_fan_in_accumulation
```

### Post-schema-change sequence

After any database schema change, always run in this order:

```bash
make migrate   # alembic upgrade head
make seed      # re-seed prompt_registry + org/brand rows
make smoke     # acceptance gate
