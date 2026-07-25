# OmniBrand Studio

**OmniBrand Studio** is an open-source, agentic content localization platform. A LangGraph pipeline generates brand-compliant content across 6 channels and 2+ locales, driven by a FastAPI backend, a real-time React frontend, and a suite of AI judges.

> **Full setup guide → [`docs/setup.md`](docs/setup.md)**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend  (Astro + React + Tailwind)   :4321 (dev)         │
│  Campaign Copilot UI — WebSocket chat + SSE pipeline events  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / WS / SSE
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI (api)  :8000                                        │
│  REST API · /auth · /campaigns · /conversations · /reviews   │
│  /knowledge · /users · /orgs · Prometheus /metrics           │
├──────────────────────────────────────────────────────────────┤
│  Worker                                                      │
│  Redis BLPOP consumer → LangGraph pipeline                   │
│  Prometheus metrics on :9091                                 │
└──┬──────────┬───────────┬───────────┬────────────────────────┘
   │          │           │           │
┌──▼──┐  ┌───▼──┐  ┌─────▼──┐  ┌────▼───────┐
│ PG  │  │Redis │  │ MinIO  │  │  ChromaDB  │
│:5432│  │:6379 │  │ :9000  │  │ (local FS) │
└─────┘  └──────┘  └────────┘  └────────────┘
┌─────────────────────────────────────────────────────────────┐
│  LiteLLM Proxy  :4000  →  Anthropic / OpenAI / Groq         │
│  Langfuse       :3001  →  LLM trace visibility              │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Prometheus :9090 · Grafana :3000 · Jaeger :16686           │
│  MailHog :8025 · MinIO Console :9001                        │
└─────────────────────────────────────────────────────────────┘
```

---

## LangGraph Pipeline

Each campaign runs through this pipeline:

```
intake_agent
  → content_generator
  → personalization_agent
  → translation_agent
  → judge_gate
  → judge_claude ┐
  → judge_gpt4o  ├── (parallel fan-out)
  → judge_llama  ┘
  → confidence_aggregator
  → reflexion
  → review_gate         ← interrupt point (human review)
  → publishing_agent    → MailHog (demo email delivery)
```

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.12, uv, asyncpg, SQLAlchemy async |
| Pipeline | LangGraph, LangGraph Checkpoint Postgres |
| LLM Gateway | LiteLLM proxy (Anthropic / OpenAI / Groq) |
| Queue | Redis BLPOP (`campaigns:queue`) |
| Database | PostgreSQL 16 |
| Vector Store | ChromaDB (local) or Pinecone (managed) |
| Object Storage | MinIO (S3-compatible) |
| Auth | RS256 JWT + API key (`X-API-Key`) |
| Observability | Prometheus, Grafana, Jaeger (OTLP), Langfuse |
| Frontend | Astro + React + Tailwind CSS v4 |

---

## Quick Start

```bash
# 1. Install Python deps
make install

# 2. Generate JWT RSA keypair
make certs

# 3. Create and fill in .env  (see docs/setup.md for all variables)
cp .env.example .env

# 4. Start all infrastructure, run migrations, seed data
make up

# 5. Start API + worker
make run      # terminal 1
make worker   # terminal 2

# 6. Start frontend
cd frontend && npm install && npm run dev   # terminal 3 → http://localhost:4321

# 7. Verify everything works
make smoke
```

Or as a single command (steps 1–4):

```bash
make setup
```

For the full setup guide including all environment variables, API keys, and configuration options, see **[`docs/setup.md`](docs/setup.md)**.

---

## Observability

| Service | URL | Purpose |
|---|---|---|
| API | http://localhost:8000/docs | REST API + Swagger UI |
| Frontend | http://localhost:4321 | Campaign Copilot UI |
| Grafana | http://localhost:3000 | Dashboards (Campaign Ops, LLM Quality, Infra, KPIs) |
| Prometheus | http://localhost:9090 | Metrics |
| Jaeger | http://localhost:16686 | Distributed traces |
| Langfuse | http://localhost:3001 | LLM traces |
| MailHog | http://localhost:8025 | Email delivery sink |
| MinIO Console | http://localhost:9001 | Object storage |

---

## Documentation

| Doc | Contents |
|---|---|
| [`docs/setup.md`](docs/setup.md) | One-time setup, configuration reference, run instructions |
| [`docs/run-and-operations-guide.md`](docs/run-and-operations-guide.md) | E2E run paths, pipeline stages, RAG ingestion, testing |
| [`docs/local-eval-developer-guide.md`](docs/local-eval-developer-guide.md) | No-Docker local eval mode |
| [`docs/intake_agent.md`](docs/intake_agent.md) | Intake agent design |
| [`docs/publish_agent.md`](docs/publish_agent.md) | Publishing agent + email template design |
| [`CLAUDE.md`](CLAUDE.md) | Agent coding guide, invariants, model aliases |

---

## License

[LICENSE](LICENSE)
