# OmniBrand Studio — Setup Guide

This guide covers everything needed to run OmniBrand Studio end-to-end:
**one-time setup**, **configuration reference**, and **how to run** the application.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [One-Time Setup](#2-one-time-setup)
3. [Configuration Reference](#3-configuration-reference)
4. [Running the Application](#4-running-the-application)
5. [Observability Endpoints](#5-observability-endpoints)
6. [Useful Commands](#6-useful-commands)
7. [Known Limitations](#7-known-limitations)

---

## 1. Prerequisites

Install the following on your developer machine before proceeding.

| Tool | Version | Required for | Install |
|---|---|---|---|
| **Docker** + **Docker Compose** | Docker ≥ 24 | All infrastructure services | [docs.docker.com](https://docs.docker.com/get-docker/) |
| **Python** | 3.12+ | Backend (enforced by `pyproject.toml`) | [python.org](https://www.python.org/downloads/) |
| **uv** | latest | Python package manager (replaces pip/poetry) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 22 (see `frontend/.nvmrc`) | Frontend dev server | [nodejs.org](https://nodejs.org/) |
| **OpenSSL** | system | JWT RSA keypair generation | Usually pre-installed on macOS/Linux |
| **honcho** | any | Optional — `make dev` (API + worker together) | `pip install honcho` or `brew install honcho` |

> **Windows users:** Use `scripts/make.ps1` in place of `make`. All commands are mirrored.

---

## 2. One-Time Setup

Run these steps once after cloning the repository. After this, you only need [Part 4](#4-running-the-application) on every start.

### Step 1 — Install Python dependencies

```bash
make install
# or: uv sync
```

### Step 2 — Generate JWT RSA keypair

```bash
make certs
```

This creates `certs/private_key.pem` (RS256 private key) and `certs/public_key.pem` (public key). The API and worker both mount these files. **Do not regenerate these after issuing tokens** — it will invalidate all active sessions.

> The `certs/` directory is already in `.gitignore`. Never commit the private key.

### Step 3 — Create and fill in `.env`

```bash
cp .env.example .env
```

Then open `.env` and fill in values. See the [Configuration Reference](#3-configuration-reference) below for a full description of every variable.

**Minimum required to start:**
- `POSTGRES_PASSWORD` — any strong password
- `MINIO_PASSWORD` — any strong password
- `LANGFUSE_SECRET` and `LANGFUSE_SALT` — any random strings
- `SECRET_KEY` — random string, minimum 32 characters
- `GROQ_API_KEY` — free-tier LLM provider (get at [console.groq.com](https://console.groq.com))

Everything else is optional for local development.

### Step 4 — Start infrastructure

```bash
make up
```

This starts all Docker services, waits for health checks, runs database migrations, and seeds the default org/brand/prompt data. It also creates the default dev admin account (`admin@omnibrand.local` / `OmniBrand!123`).

**What starts:**

| Service | Port(s) | Purpose |
|---|---|---|
| PostgreSQL | 5432 | Primary DB + LangGraph checkpoints |
| Redis | 6379 | Campaign queue + LiteLLM cache |
| MinIO | 9000, 9001 | Object storage (brand assets) |
| LiteLLM | 4000 | LLM proxy (routes to Anthropic/OpenAI/Groq) |
| Langfuse | 3001 | LLM trace visibility |
| Prometheus | 9090 | Metrics |
| Grafana | 3000 | Dashboards |
| Jaeger | 16686, 4317, 4318 | Distributed tracing |
| MailHog | 1025 (SMTP), 8025 (UI) | Email delivery sink |
| API | 8000 | FastAPI application |
| Worker | — (metrics: 9091) | LangGraph pipeline consumer |

### Step 5 — Langfuse first-run (optional)

If you want LLM traces, visit [http://localhost:3001](http://localhost:3001) after `make up`, create an account, create a project, and copy the **Public Key** and **Secret Key** into `.env`:

```
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
```

Then restart the API and worker. If left blank, the system uses a no-op null client — everything works, but no LLM traces are recorded.

### Step 6 — Install frontend dependencies

```bash
cd frontend && npm install
```

### One-shot alternative (Steps 1–4)

```bash
make setup
```

This runs `install → certs → up` in one command. You still need to create `.env` before running it.

---

## 3. Configuration Reference

### 3.1 Backend `.env` Variables

All variables are read from `.env` at the repo root by `backend/core/config.py`. Copy `.env.example` as your starting point.

#### Infrastructure (Required)

| Variable | Default in example | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | `changeme_postgres_32chars` | PostgreSQL password. Used in all DSNs. |
| `MINIO_PASSWORD` | `changeme_minio_16chars` | MinIO root password. |
| `LANGFUSE_SECRET` | `changeme_langfuse_secret_32chars` | Langfuse NextAuth secret. |
| `LANGFUSE_SALT` | `changeme_langfuse_salt_16chars` | Langfuse password hash salt. |
| `SECRET_KEY` | `changeme_app_secret_32chars_minimum` | FastAPI app signing key (≥ 32 chars). |

#### LLM API Keys

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | **Required** (free tier) | Free-tier generation, judges, translation. Get at [console.groq.com](https://console.groq.com) |
| `ANTHROPIC_API_KEY` | Optional (paid tier) | `gen-premium`, `judge-1`, `eval-model`. Only needed if `JUDGE_TIER=paid`. |
| `OPENAI_API_KEY` | Optional (paid tier) | `judge-2`, `embedding`. Only needed if `JUDGE_TIER=paid`. |
| `GEMINI_API_KEY` | Optional | Fallback for `util-fast`, `brief-collector`, `understanding`, `responder-chat`. |
| `DEEPL_API_KEY` | Optional | DeepL translation escalation. |
| `HF_TOKEN` | Optional | Hugging Face token for private model downloads. |

#### Observability

| Variable | Default | Description |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | `""` | Langfuse project public key. Leave blank to disable LLM traces. |
| `LANGFUSE_SECRET_KEY` | `""` | Langfuse project secret key. |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin panel password. |

#### Vector Store

| Variable | Default | Description |
|---|---|---|
| `VECTOR_STORE_BACKEND` | `chroma` | `"chroma"` (local) or `"pinecone"` (managed). |
| `PINECONE_API_KEY` | `""` | Required only if `VECTOR_STORE_BACKEND=pinecone`. |
| `PINECONE_ENVIRONMENT` | `""` | Pinecone environment string. |
| `PINECONE_INDEX` | `omnibrand-guides` | Pinecone index name. |

#### Publishing (Email delivery)

| Variable | Default | Description |
|---|---|---|
| `PUBLISH_RECIPIENT_EMAILS` | `""` | Comma-separated email list. Leave blank to skip delivery (pipeline still completes). |

#### LLM Judge Tier

| Variable | Default | Description |
|---|---|---|
| `JUDGE_TIER` | `free` | `"free"` = Groq cross-family panel (no paid spend). `"paid"` = Claude/GPT-4o/Groq panel (requires `ANTHROPIC_API_KEY` + `OPENAI_API_KEY`). |

Switching from `free` to `paid` also requires re-running judge calibration:
```bash
cd backend && uv run python scripts/calibrate_judges.py
```

#### Auth

The backend uses **RS256 JWT** (generated by `make certs`) and **API key** (`X-API-Key` header) authentication. Both paths are supported simultaneously. The RSA keys are read from `certs/private_key.pem` and `certs/public_key.pem` — these must exist before starting the API.

| Variable | Default | Description |
|---|---|---|
| `JWT_PRIVATE_KEY_PATH` | `./certs/private_key.pem` | RS256 private key path. |
| `JWT_PUBLIC_KEY_PATH` | `./certs/public_key.pem` | RS256 public key path. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | JWT access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token lifetime. |

#### Dev Bootstrap

| Variable | Default | Description |
|---|---|---|
| `DEV_BOOTSTRAP_ADMIN_ENABLED` | `1` | Create the default admin on startup. |
| `DEV_ADMIN_EMAIL` | `admin@omnibrand.local` | Default admin email. |
| `DEV_ADMIN_PASSWORD` | `OmniBrand!123` | Default admin password. |
| `DEV_ADMIN_ORG_ID` | `00000000-0000-0000-0000-000000000001` | Seeded org UUID. |
| `DEV_ADMIN_BRAND_ID` | `00000000-0000-0000-0000-000000000002` | Seeded brand UUID. |

### 3.2 Frontend `.env` Variables

Create `frontend/.env` by copying `frontend/.env.example`. All variables are prefixed `PUBLIC_` (bundled into the browser build).

| Variable | Default | Description |
|---|---|---|
| `PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend API URL. |
| `PUBLIC_API_KEY` | `""` | API key. On localhost, auto-falls-back to `dev-local-chat-key` if blank. |
| `PUBLIC_DEFAULT_BRAND_ID` | `00000000-0000-0000-0000-000000000002` | Default brand for new conversations. Matches seed data. |
| `PUBLIC_ADMIN_PASSWORD` | `firefly` | Admin panel demo password (client-side gate only). |

---

## 4. Running the Application

### 4.1 Backend (API + Worker)

Start each in its own terminal from the repo root:

```bash
# Terminal 1 — FastAPI on :8000
make run

# Terminal 2 — Worker (LangGraph pipeline consumer)
make worker
```

Or run both together with honcho:

```bash
make dev
```

### 4.2 Frontend

```bash
cd frontend && npm run dev
# → http://localhost:4321
```

The frontend is a fully connected React SPA. It communicates with the backend at `PUBLIC_API_BASE_URL` (default `http://localhost:8000`) using:
- **HTTP** — REST API calls (`/auth`, `/campaigns`, `/knowledge`, etc.)
- **WebSocket** — Real-time conversation chat (`/conversations/{id}`)
- **Server-Sent Events** — Live pipeline event stream (`/campaigns/{id}/stream`)

### 4.3 Verify End-to-End

```bash
make smoke
```

This runs the acceptance gate: pushes 20 dummy campaigns through the Redis queue, checks all observability signals, and verifies the Prometheus/Grafana/Jaeger stack is healthy.

### 4.4 Send a Campaign via the API

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

Then watch the pipeline run at [http://localhost:16686](http://localhost:16686) (Jaeger) and [http://localhost:8025](http://localhost:8025) (MailHog for output emails).

### 4.5 Post-Schema-Change Workflow

After any database schema change, always run in this order:

```bash
make migrate   # alembic upgrade head
make seed      # re-seed prompt_registry + org/brand rows
make smoke     # acceptance gate
```

---

## 5. Observability Endpoints

All services are available locally after `make up`:

| Service | URL | Credentials |
|---|---|---|
| **API** (REST + Swagger) | http://localhost:8000/docs | API key or JWT |
| **Frontend** (Campaign Copilot) | http://localhost:4321 | Login: `admin@omnibrand.local` / `OmniBrand!123` |
| **Grafana** (Dashboards) | http://localhost:3000 | `admin` / `$GRAFANA_ADMIN_PASSWORD` |
| **Prometheus** (Metrics) | http://localhost:9090 | — |
| **Jaeger** (Traces) | http://localhost:16686 | — |
| **Langfuse** (LLM Traces) | http://localhost:3001 | Create account on first visit |
| **MailHog** (Email sink) | http://localhost:8025 | — |
| **MinIO Console** (Storage) | http://localhost:9001 | `omnibrand` / `$MINIO_PASSWORD` |

---

## 6. Useful Commands

```bash
make up              # Start all Docker services
make down            # Stop all services (keeps volumes)
make down-reset      # Stop all services and delete volumes (full reset)
make logs            # Tail API + worker logs
make run             # Start API locally (port 8000)
make worker          # Start worker locally
make dev             # Start API + worker together (honcho)
make migrate         # Run database migrations (alembic upgrade head)
make seed            # Seed prompt_registry + org/brand rows
make smoke           # End-to-end acceptance gate
make test            # Run backend test suite
make lint            # ruff check + mypy
make format          # ruff format + ruff check --fix
make migrate-history # Show migration history
make certs           # (Re)generate JWT RSA keypair
```

---

## 7. Known Limitations

The following are known gaps in the current implementation:

| Limitation | Notes |
|---|---|
| **DLQ has no consumer** | `campaigns:dead_letter` accumulates failed campaigns. Inspect manually: `redis-cli lrange campaigns:dead_letter 0 -1` |
| **`audit_log` partitions expire** | Only `audit_log_2025` and `audit_log_2026` partitions exist. A new migration adding `audit_log_2027` must be created before 2027-01-01. |
| **Frontend admin panel is a demo gate** | `PUBLIC_ADMIN_PASSWORD` is a client-side password check — not real security. Replace with server-side auth for production. |
| **Langfuse first-run requires manual account creation** | Visit http://localhost:3001 after `make up` to create an account before keys are available. |
| **`scripts/make.ps1` is manually maintained** | The Windows PowerShell equivalent of `Makefile` targets must be manually kept in sync when Makefile changes. |
