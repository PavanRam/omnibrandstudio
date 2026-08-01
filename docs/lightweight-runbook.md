# Lightweight System Runbook

This runbook covers the default six-service OmniBrand Studio stack:

- PostgreSQL
- Redis
- LiteLLM
- MailHog
- FastAPI
- LangGraph worker

Grafana, Prometheus, Jaeger, Langfuse, exporters, and MinIO are not started in
lightweight mode.

## 1. Prerequisites

Run commands from the repository root.

Required software:

- Docker Desktop with Docker Compose
- Python 3.12 and `uv`
- NVM with Node 22.12.0 for the frontend

Create the local configuration if it does not exist:

```bash
cp .env.example .env
```

Generate JWT keys:

```bash
make certs
```

## 2. First-Time Start

Install Python dependencies, generate JWT keys, start the lightweight stack,
run migrations, and seed development data:

```bash
make fresh-start
```

If dependencies and keys are already present:

```bash
make up
```

`make up` starts the six lightweight services, waits for readiness, applies
database migrations, seeds prompts and development records, and creates or
updates the development administrator.

## 3. Daily Commands

### Start

```bash
make up
```

### Stop

```bash
make down
```

This preserves PostgreSQL and Redis volumes.

### Restart

```bash
make restart
```

This performs a normal stop followed by `make up`, including migration and seed
checks.

To restart only the existing containers without rerunning setup:

```bash
docker compose restart postgres redis litellm mailhog api worker
```

### Show container status

```bash
docker compose ps
```

The expected lightweight services are:

```text
api
litellm
mailhog
postgres
redis
worker
```

## 4. Frontend

Start the Astro frontend:

```bash
make frontend
```

The launcher automatically loads NVM and selects Node 22.12.0. Open:

```text
http://localhost:4321
```

Check frontend status or logs:

```bash
cd frontend
npm run astro -- dev status
npm run astro -- dev logs
```

Stop the frontend:

```bash
cd frontend
npm run astro -- dev stop
```

Build and test the frontend:

```bash
cd frontend
npm test
npm run build
```

## 5. Service URLs

| Service | URL |
|---|---|
| API | <http://localhost:8000> |
| OpenAPI documentation | <http://localhost:8000/docs> |
| LiteLLM | <http://localhost:4000> |
| MailHog | <http://localhost:8025> |
| Frontend | <http://localhost:4321> |

## 6. Health and Acceptance Checks

Check API health:

```bash
curl http://localhost:8000/health
```

Check application metrics:

```bash
curl http://localhost:8000/metrics
```

Run the lightweight acceptance gate:

```bash
make smoke
```

The smoke gate verifies API health, application metrics, persisted campaign
processing, and matching dead-letter outcomes. A campaign may legitimately
stop at `awaiting_review`.

Require a completed publishing flow and MailHog delivery:

```bash
uv run python scripts/smoke_test.py --lite --require-publishing
```

## 7. Logs

Stream all six lightweight services:

```bash
make logs
```

Logs are displayed in the terminal and appended to:

```text
logs/omnibrand.log
```

Use a different output file:

```bash
make logs LOG_FILE=logs/debug-session.log
```

Inspect recent logs without following:

```bash
docker compose logs --tail=200 --timestamps \
  postgres redis litellm mailhog api worker
```

Follow selected services:

```bash
docker compose logs -f --tail=200 api worker litellm
```

Search for common failures:

```bash
rg "error|failed|exception|degraded_hash" logs/omnibrand.log
```

## 8. Trace a Request Without Jaeger or Langfuse

Lightweight tracing uses correlation identifiers:

```text
X-Request-ID -> campaign_id -> worker and agent logs
```

For a UI request, copy the `X-Request-ID` response header from browser
Developer Tools, then search:

```bash
rg "REQUEST_ID_HERE" logs/omnibrand.log
```

Find the corresponding `campaign_id`, then follow the whole campaign:

```bash
rg "CAMPAIGN_ID_HERE" logs/omnibrand.log
```

Follow both identifiers live:

```bash
tail -f logs/omnibrand.log |
  rg --line-buffered "REQUEST_ID_HERE|CAMPAIGN_ID_HERE"
```

## 9. Queue and Campaign Diagnostics

Check the campaign queue:

```bash
docker compose exec redis redis-cli LLEN campaigns:queue
```

Check the dead-letter queue:

```bash
docker compose exec redis redis-cli LLEN campaigns:dead_letter
docker compose exec redis redis-cli LRANGE campaigns:dead_letter 0 -1
```

Inspect recent campaigns:

```bash
docker compose exec postgres psql -U omnibrand -d omnibrand \
  -c "SELECT id, status, created_at, started_at, completed_at
      FROM campaigns
      ORDER BY created_at DESC
      LIMIT 10;"
```

Inspect one campaign:

```bash
docker compose exec postgres psql -U omnibrand -d omnibrand \
  -c "SELECT * FROM campaigns WHERE id = 'CAMPAIGN_ID_HERE';"
```

## 10. Common Recovery Commands

Restart only the application processes:

```bash
docker compose restart api worker
```

Restart LiteLLM:

```bash
docker compose restart litellm
```

Rebuild the lightweight backend image after dependency changes:

```bash
docker compose build api worker
make restart
```

Reapply migrations:

```bash
make migrate-docker
```

Reseed prompts and development data:

```bash
make seed
make seed-admin
```

## 11. Destructive Reset

The following command deletes local Docker volumes, including PostgreSQL data:

```bash
make down-reset
```

Only use it when losing local campaigns, checkpoints, users, prompts, and other
development data is acceptable. Start again with:

```bash
make up
```

## 12. Embedding Behavior

The lightweight image does not include sentence-transformers or torch.
Semantic embeddings use LiteLLM's `embedding` alias.

If its provider key is missing or the hosted embedding call fails, the
application logs:

```text
embedding_hosted_failed_using_degraded_hash
```

Search for degraded retrieval:

```bash
rg "embedding_hosted_failed_using_degraded_hash" logs/omnibrand.log
```

Configure the provider key and re-ingest retained RAG content before depending
on semantic retrieval quality.

## 13. Switch to the Full Stack

Start observability and storage services:

```bash
make up-full
```

Run the full acceptance gate:

```bash
make smoke-full
```

Return to lightweight mode:

```bash
make down
make up
```

