# OmniBrand Studio — Phase 0 Implementation Deep Dive

This document is a granular technical record of the Phase 0 foundation as it exists on disk today. Every code excerpt below is copied verbatim from the live repository — nothing is paraphrased or reconstructed from memory. RSA/JWT RS256 auth is documented exactly as implemented; it is intentionally retained and is **not** a candidate for removal.

---

## 1. Operational Automation & Build Layer (`Makefile`)

### What

`Makefile` (repo root) defines 19 phony targets, declared up front:

```makefile
.PHONY: install install-dev run worker dev test test-unit test-integration smoke lint format migrate migrate-down migrate-history seed up down logs certs setup
```

Target-by-target, with literal command bodies:

| Target | Command(s) |
|---|---|
| `install` | `uv sync` |
| `install-dev` | `uv sync --dev` |
| `run` | `cd backend && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload` |
| `worker` | `cd backend && uv run python -m worker.main` |
| `dev` | `honcho start` |
| `test` | `cd backend && uv run pytest tests/ -v --timeout=60` |
| `test-unit` | `cd backend && uv run pytest tests/unit/ -v` |
| `test-integration` | `cd backend && uv run pytest tests/integration/ -v --timeout=120` |
| `smoke` | `uv run python scripts/smoke_test.py` |
| `lint` | `cd backend && uv run ruff check .` then `cd backend && uv run mypy . --ignore-missing-imports` |
| `format` | `cd backend && uv run ruff format .` then `cd backend && uv run ruff check . --fix` |
| `migrate` | `cd backend && uv run alembic upgrade head` |
| `migrate-down` | `cd backend && uv run alembic downgrade -1` |
| `migrate-history` | `cd backend && uv run alembic history` |
| `seed` | `cd backend && uv run python ../scripts/seed_prompts.py` |
| `up` | `docker compose up -d --wait` |
| `down` | `docker compose down -v` |
| `logs` | `docker compose logs -f api worker` |
| `certs` | `mkdir -p certs && openssl genrsa -out certs/private_key.pem 2048 && openssl rsa -in certs/private_key.pem -pubout -out certs/public_key.pem && chmod 600 certs/private_key.pem` |
| `setup` | composite: `install certs up migrate seed` (declared as prerequisites, executed in that order by `make`) |

Note `test-unit`/`test-integration` reference `tests/unit/` and `tests/integration/` subdirectories that do not exist yet — only `backend/tests/test_pipeline_skeleton.py` and `backend/tests/conftest.py` are present at the top level of `tests/`. These two targets are forward-declared for a test-suite split that hasn't happened yet.

The Windows-native equivalent, `scripts/make.ps1`, mirrors every target (including `certs`) via a `switch ($Target)` block, each branch wrapping `Push-Location backend / try { ... } finally { Pop-Location }` where the Makefile used `cd backend &&`. `setup` inlines the full chain (`uv sync` → `generate_certs.ps1` → `docker compose up -d --wait` → `alembic upgrade head` → `seed_prompts.py`) rather than depending on other cases, since PowerShell's `switch` has no target-dependency mechanism analogous to Make's prerequisite list.

### Why

- **`.PHONY`** is declared because every target name (`install`, `test`, `up`, etc.) names an action, not a file `make` should treat as a build artifact — without `.PHONY`, a same-named file (e.g. a directory literally called `test`) would shadow the target and `make` would skip it as "already up to date."
- **Thin wrappers around `uv run`/`docker compose`/`alembic`** rather than embedding logic in shell scripts: every target is a one-to-three-line pass-through, so the Makefile is a discoverable table of contents for "what can I run," not a place where behavior is hidden. Anyone reading `make lint` sees the exact `ruff`/`mypy` invocation, not an opaque script call.
- **`cd backend &&` per-target** rather than a global `cd` at the top of the Makefile: `pyproject.toml`/`uv.lock` live at the repo root (see §3), but the actual Python package (`api`, `core`, `pipeline`, etc.) lives under `backend/`, and tools like `pytest`/`ruff`/`alembic` need their working directory to be `backend/` to resolve relative imports and `alembic.ini`'s `script_location = alembic`. `uv run` at the repo root still resolves the root `.venv`, so `cd backend && uv run ...` gets both the right venv and the right working directory.
- **`setup: install certs up migrate seed`** encodes the exact bootstrap order a new developer needs — dependencies before secrets before infrastructure before schema before data — as a declarative dependency list rather than a bash script with manual sequencing.

### Implications

- **Onboarding velocity**: a new developer's entire ramp-up is `make setup` (or `scripts/make.ps1 setup` on native Windows) followed by `make run` + `make worker`. No tribal knowledge of "run alembic then seed then generate certs" is required — it's encoded once.
- **Cognitive load**: because every target is a near-literal command, there's no Makefile-specific DSL to learn beyond `.PHONY` and prerequisite lists — a developer who has never seen this Makefile can `cat` it and understand every target in under a minute.
- **Deterministic quality gates**: `lint` chains `ruff check` and `mypy` unconditionally (`make` stops on the first non-zero exit by default), so `make lint` cannot report success if either tool fails — this is the same guarantee a pre-commit hook or CI job would rely on, just invoked manually today.
- **Parity gap risk**: because `scripts/make.ps1` is a hand-maintained mirror of the Makefile rather than generated from it, every new Makefile target must be manually ported to the PowerShell switch statement or Windows-native contributors silently lose access to it.

---

## 2. Production Runtime Configuration (`Procfile`)

### What

`Procfile` (repo root), two lines, verbatim:

```
web:    uv run uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
worker: uv run python -m worker.main
```

- `web` binds `0.0.0.0` (all interfaces — required inside a container/dyno where the host network namespace isn't the same as the process's), reads `$PORT` with a `8000` fallback (`${PORT:-8000}` is POSIX shell parameter expansion, honoring platforms like Heroku/Render that inject `$PORT` dynamically), and passes `--workers 4` to Uvicorn's built-in multi-worker mode.
- `worker` has no flags — it's a single long-running asyncio process (`backend/worker/main.py`'s `main()` coroutine, an infinite `BLPOP` loop; see §9), so there is no concept of "workers 4" for it — process-level horizontal scaling for the worker means running multiple `worker` dynos/replicas, not multiple threads within one.

This is distinct from `docker-compose.yml`'s `api`/`worker` service `command:` fields, which hardcode `--port 8000` (no `$PORT`) and add `--reload` for the API — the `Procfile` is the production/dyno-style declaration; `docker-compose.yml` is the local dev declaration. They are two independent runtime configurations, not one wrapping the other.

### Why

- **`uv run` wrapping the entrypoint in production**, not just locally: `uv run` resolves the `.venv` created by `uv sync --frozen` (see the `backend/Dockerfile`, §3) without requiring `source .venv/bin/activate` or `PATH` manipulation in the process manager's environment. Because the two-stage Dockerfile already sets `ENV PATH="/app/.venv/bin:$PATH"` in the runtime stage, `uv run` here is technically redundant with a bare `uvicorn` call inside that container — but keeping it means the `Procfile` is portable to any `uv`-aware host (Heroku's Python buildpack understands `Procfile` + `uv`, so does Railway) without depending on the container having pre-activated the venv via `ENV PATH`.
- **No `--reload`** on the `Procfile`'s `web` line (unlike the docker-compose `api` service): `--reload` spawns a file-watcher and reloader subprocess, which is dev-only overhead and a correctness risk in production (a reload triggered by an unexpected file write mid-request would kill in-flight connections).

### Implications

- **Container layer weight**: the `Procfile` itself adds zero image weight — it's a 2-line text file read by the process manager, not baked into image layers. The actual weight optimization lives in `backend/Dockerfile`'s two-stage split (§3): the `builder` stage's `uv sync` cache and pip wheel artifacts never reach the `runtime` image, only the resolved `.venv` directory is copied across (`COPY --from=builder /app/.venv /app/.venv`).
- **Execution performance overhead**: negligible — `uv run` does a fast venv-path resolution (`uv` is written in Rust and this operation is sub-millisecond) before exec'ing the real `uvicorn`/`python` process; there is no ongoing wrapper process once the target command starts (`uv run` execs, it doesn't fork-and-monitor).
- **Crash/reboot behavior**: neither process type has internal supervision — if `uvicorn --workers 4`'s parent process dies, all 4 workers die with it; if the `worker` process's `main()` raises outside its `try/except` (see §9 — currently only exceptions from `process_campaign()` are caught, not e.g. Redis connection failures during `blpop`), the entire process exits. Restart-on-crash is delegated entirely to whatever external supervisor runs the `Procfile` (Heroku's dyno manager, `honcho` locally does not auto-restart, systemd, k8s, etc.) — there is no retry/backoff logic in the codebase itself.
- **Web concurrency scaling**: `--workers 4` gives 4 OS-level worker processes under one Uvicorn master, each running its own asyncio event loop and its own copy of the FastAPI app (including its own `_engine`/`_redis`/`_qdrant` singletons from `core/database.py` etc. — see §7, these are process-global module variables, so each worker has independent connection pools, not a shared one). Scaling beyond 4 means either raising the flag or running multiple dynos/containers behind a load balancer — nothing in the `Procfile` line auto-scales based on load.

---

## 3. Package Management & Dependency Architecture (`uv` & `pyproject.toml`)

### What

Full `pyproject.toml` (repo root), section by section:

```toml
[project]
name = "omnibrand"
version = "0.1.0"
description = "OmniBrand Studio — agentic content platform"
requires-python = ">=3.12"

dependencies = [
    # web
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-multipart>=0.0.12",

    # database
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",  # required by langgraph-checkpoint-postgres

    # cache / queue
    "redis[hiredis]>=5.2",

    # vector store
    "qdrant-client>=1.13",

    # auth
    "python-jose[cryptography]>=3.3",
    "bcrypt>=4.2",
    "passlib>=1.7",

    # ai / llm
    "langchain-core>=0.3",
    "langgraph>=0.2",
    "langgraph-checkpoint-postgres>=2.0",
    "litellm>=1.55",
    "langfuse>=2.0",
    "openai>=1.59",
    "anthropic>=0.42",

    # observability
    "prometheus-client>=0.21",
    "opentelemetry-sdk>=1.29",
    "opentelemetry-exporter-otlp>=1.29",

    # config
    "pydantic>=2.10",
    "pydantic-settings>=2.7",

    # utilities
    "python-dotenv>=1.0",
    "httpx>=0.28",
    "anyio>=4.7",
    "structlog>=24.4",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["backend"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.32",
    "ruff>=0.8",
    "mypy>=1.13",
    "types-redis>=4.6",
    "types-passlib>=1.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["backend/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

- **`dependencies`** is a single flat array grouped by inline `#` comments
  (`web`, `database`, `cache / queue`, `vector store`, `auth`, `ai / llm`,
  `observability`, `config`, `utilities`) — there is no PEP 621
  `[project.optional-dependencies]` split. Presidio and
  `sentence-transformers` were removed after usage analysis; hosted embeddings
  now go through LiteLLM and TF-IDF is the primary lightweight reranker.
- **`[tool.hatch.build.targets.wheel] packages = ["backend"]`** is the one non-default build-system override. Without it, `hatchling` (the configured build backend) cannot locate an importable package to ship in the wheel, because the project is named `omnibrand` but the actual Python package tree lives under `backend/` (i.e. `backend/api`, `backend/core`, `backend/pipeline`, ...) rather than a top-level `omnibrand/` directory.
- **`[dependency-groups] dev`** (PEP 735 syntax, not the legacy `[tool.uv] dev-dependencies` key) holds test/lint/type tooling, installed only via `uv sync --dev`.
- **`[tool.pytest.ini_options] testpaths = ["backend/tests"]`** lets `pytest` be invoked from the repo root and still discover `backend/tests/test_pipeline_skeleton.py` without needing `cd backend` first (this is independent of the Makefile's `cd backend &&` convention, which exists for other reasons — see §1).
- **`[tool.mypy] strict = true`** — full strict-mode type checking is turned on for the whole `backend/` tree, not opted into per-module.

### Bug Found & Fix: hatchling wheel packaging

During the initial `uv sync`, the build failed with:

```
ValueError: Unable to determine which files to ship inside the wheel...
The most likely cause of this is that there is no directory that matches
the name of your project (omnibrand).
```

Root cause: `hatchling`'s default wheel-packaging heuristic looks for a directory named after `[project].name` (`omnibrand/`) to auto-detect the package. This repo's actual code lives in `backend/`. Fix: added the `[tool.hatch.build.targets.wheel] packages = ["backend"]` block shown above, which explicitly tells `hatchling` to treat `backend/` as the shippable package root. This is a build-metadata fix only — it does not change any import paths, since code always imported as `from core.config import settings` etc. (relative to `backend/` being on `PYTHONPATH`/CWD), never as `from backend.core.config import settings`.

### Why (uv vs. pip/poetry)

- **Single resolved lockfile (`uv.lock`)** committed to the repo is the
  deliberate replacement for `requirements.txt` + no-lock pip installs, or
  Poetry's `poetry.lock`. Removing Presidio and `sentence-transformers` also
  removes the spaCy and torch/transformers/CUDA dependency trees from the
  resolved runtime.
- **`uv sync --frozen`** (used in `backend/Dockerfile`'s builder stage) fails the build outright if `uv.lock` is stale relative to `pyproject.toml`, rather than silently re-resolving — this converts "lockfile drift" from a runtime surprise into a build-time hard failure.
- **Rust-backed resolver speed**: `uv`'s dependency resolver and installer are compiled, not a Python script — full resolution of this project's ~35 direct dependencies into a locked graph completes in low single-digit seconds, and `uv sync` on a warm cache (unchanged lockfile) completes in under 2 seconds, as observed during this build (`Resolved 166 packages in 2ms` on a re-run with no changes).
- **No manual venv activation**: every command in this repo is prefixed `uv run`, which transparently creates/uses `.venv/` and resolves the correct interpreter — eliminating the class of bugs where a developer's shell has stale `PATH`/`VIRTUAL_ENV` state from a different project's venv.

### Implications

- **Environment reproducibility**: identical `uv.lock` + identical `pyproject.toml` guarantees identical resolved versions across every developer machine and CI runner — there is no "works on my machine" caused by transitive-dependency drift, which is a real risk with unpinned `requirements.txt`.
- **Production build speed**: the Dockerfile's `builder` stage only re-runs `uv sync --frozen` when `pyproject.toml`/`uv.lock` change (Docker layer caching keys off the `COPY pyproject.toml uv.lock ./` step) — application code changes in `COPY . .` (runtime stage) never invalidate the dependency-install layer.
- **Dependency conflict mitigation**: `uv`'s resolver produces one consistent solve for the whole graph up front (visible in the `uv sync` output: `Resolved 166 packages`), rather than pip's historically weaker resolver that could silently install an incompatible transitive version.
- **Storage footprint**: `uv`'s global package cache (`~/.local/share/uv` / `%LOCALAPPDATA%\uv`) is content-addressed and shared across all projects on a machine — installing the same `pydantic==2.13.4` for two different `uv`-managed projects does not duplicate the wheel on disk, unlike per-venv pip installs.
- **`mypy strict = true` implication**: every new module added to `backend/` must satisfy strict type checking (no implicit `Any`, all functions must be fully annotated) from day one — this is a standing constraint on all future code, not just Phase 0's.

---

## 4. Infrastructure & Service Topology (`docker-compose.yml` + `infra/`)

### What

`docker-compose.yml` now uses profiles to keep the normal development runtime
small:

| Profile | Services | Command |
|---|---|---|
| default | `postgres`, `redis`, `litellm`, `mailhog`, `api`, `worker` | `make up` |
| `observability` | `langfuse-db-init`, `langfuse`, `prometheus`, `grafana`, `jaeger`, `redis-exporter`, `postgres-exporter` | `make up-full` |
| `storage` | `minio`, `createbuckets` | `make up-full` |

The default target sets `COMPOSE_OTEL_ENABLED=0`, preventing background
exports to an absent Jaeger service. `make up-full` sets it to `1` and enables
both optional profiles. `api` and `worker` still depend only on healthy
Postgres and Redis; LiteLLM depends on healthy Redis. MailHog remains in the
default set because SMTP publishing is part of the application flow.

`api`/`worker` build config: `build: {context: ., dockerfile: backend/Dockerfile, target: runtime}` — the build **context is the repo root** (`.`), not `./backend`, with an explicit `dockerfile:` pointer into `backend/`. This is necessary because `pyproject.toml`/`uv.lock` (which the Dockerfile's `COPY pyproject.toml uv.lock ./` step needs) live at the repo root, not inside `backend/`.

`infra/litellm/litellm_config.yaml` defines 8 named model aliases (`gen-premium` with two competing providers under the same alias for fallback, `gen-free`, `judge-1`/`judge-2`/`judge-3` pinned to specific model families "never change family on fallback", `util-fast`, `eval-model`, `embedding`), plus:

```yaml
router_settings:
  retry_policy:
    BadRequestError: {num_retries: 0}
    RateLimitError: {num_retries: 3, retry_after: 60}
    ServiceUnavailableError: {num_retries: 3}

litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
    ttl: 3600
  drop_params: true
  max_budget: 10.0
  budget_duration: "1d"
```

`infra/prometheus/prometheus.yml` scrapes two static targets, `api:8000` (`/metrics`) and `worker:9091` (no `/metrics` endpoint currently implemented on the worker — this target will show as down until worker-side metrics exposure is added). `infra/grafana/provisioning/` wires a single Prometheus datasource (`http://prometheus:9090`) and an empty dashboard-provider pointing at its own provisioning folder. `infra/nginx/nginx.conf` is an unused reverse-proxy config (proxies `/` to `api:8000`) — no `nginx` service is actually declared in `docker-compose.yml`, so this file is currently dead configuration, present for a future ingress layer.

### Bug Found & Fix: Qdrant healthcheck

Original healthcheck (per the initial spec) was `curl -sf http://localhost:6333/healthz`. On boot, `docker inspect` showed `unhealthy` with `ExitCode: 127`, `Output: "/bin/sh: 1: curl: not found"` — the `qdrant/qdrant` image does not ship a `curl` binary. Fix: replaced with a `bash`-native TCP probe (`bash` is present in that image): `test: ["CMD-SHELL", "bash -c '</dev/tcp/localhost/6333' || exit 1"]`. This checks only that the port accepts a TCP connection, not that the HTTP API is semantically healthy — a weaker but portable check.

### Why

- **`depends_on: condition: service_healthy`** (rather than plain `depends_on: [service]`) is used everywhere a real startup-order dependency exists (e.g. `api`/`worker` must not attempt `asyncpg`/`redis` connections before Postgres/Redis are accepting connections) — Compose's plain list form only waits for the container process to start, not for the service inside it to be ready, which would otherwise produce intermittent "connection refused" failures on `docker compose up`.
- **`createbuckets` as a one-shot `minio/mc` container** rather than application-level bucket creation: bucket provisioning is infrastructure setup, not applicaton runtime logic — keeping it in Compose means `docker compose up -d --wait` alone guarantees the bucket exists, with no dependency on the API/worker code ever running.
- **LiteLLM's Redis-backed response cache + `max_budget`/`budget_duration`**: centralizes both cost control and response caching at the gateway layer rather than in each caller — every agent that eventually calls `traced_llm_call()` (§9) automatically benefits from caching and budget enforcement without any agent-side code for either concern.

### Implications

- **Blast radius of the Qdrant fix**: the `/dev/tcp` check only proves the TCP listener is up, not that Qdrant's collections are queryable — `check_qdrant_health()` in `core/qdrant.py` (§7) does a real `get_collections()` call, which is the actual application-level health signal; the Compose healthcheck is a coarser, container-startup-only gate.
- **`grafana`'s weak dependency on `prometheus`**: because `prometheus` has no `healthcheck:`, Grafana can start and be marked "up" before Prometheus is actually serving `/api/v1/query`, meaning the Grafana datasource may show as unreachable for a few seconds after `docker compose up` — this is a latent (mostly harmless, self-healing) gap.
- **Build context change (root vs. `./backend`)**: any future addition to the Dockerfile that assumes files exist relative to `./backend` as the build root would break — the context is now the whole repo, so `.dockerignore` (not currently present) would need repo-root-relative patterns if introduced.
- **`infra/nginx/nginx.conf` dead code**: it documents an intended ingress layer but has zero effect on the running stack today; a future engineer must either wire it into `docker-compose.yml` as an `nginx` service or remove it to avoid confusion.

---

## 5. Database Schema & Migrations

### What

`backend/alembic.ini` sets `script_location = alembic`, `prepend_sys_path = .`. `backend/alembic/env.py` uses an **async** SQLAlchemy engine (`async_engine_from_config` + `connection.run_sync(do_run_migrations)`), driven by a dual-DSN resolution function:

```python
def get_url() -> str:
    # ALEMBIC_DSN takes precedence — migrations that touch REVOKE/GRANT on
    # audit_log require a role that owns the table (see 001_core_schema.py),
    # which may differ from the app runtime POSTGRES_DSN.
    return (
        os.environ.get("ALEMBIC_DSN")
        or os.environ.get("POSTGRES_DSN")
        or "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand"
    )
```

`backend/alembic/versions/001_core_schema.py` is the single migration (`revision = "001"`, `down_revision = None`) creating, **in this literal order** (FK-dependency order):

1. `orgs` (top-level tenant; `status`/`tier` CHECK constraints; `config`/`feature_flags` JSONB)
2. `brands` (FK → `orgs`, `ON DELETE CASCADE`)
3. `users` (FK → `orgs`; `roles TEXT[]`, `brand_ids UUID[]`; `status` CHECK)
4. `user_sessions` (FK → `users`; partial index `WHERE revoked_at IS NULL`)
5. `api_keys` (FK → `orgs`, `brands`, `users[created_by]`; `key_hash` unique, `scopes TEXT[]`)
6. `campaigns` (FK → `orgs`, `brands`, `users[created_by]`; `status` CHECK with 7 states; partial index on `status IN ('queued','running')`)
7. `brand_guides`, `terminology_entries`, `brand_claims` (all FK → `brands`)
8. `prompt_registry` (optional FK → `orgs` for org-specific overrides; unique partial index `idx_prompt_active` enforcing only one `status='active'` row per `(name, org_id)`)
9. `golden_dataset`, `prompt_experiments`, `prompt_experiment_outcomes`
10. `content_variants` (FK → `campaigns`, `ON DELETE CASCADE`)
11. `brand_scores`, `aggregated_scores` (FK → `content_variants`; `aggregated_scores.variant_id` is `UNIQUE` — one aggregate row per variant)
12. `review_requests`, `publication_receipts` (FK → `content_variants`, `campaigns`)
13. `campaign_cost_attribution` (FK → `campaigns`, `orgs`, `brands`)
14. `audit_log` — partitioned, described below
15. `omnibrand_app` REVOKE/GRANT block (immutability)

Exact `audit_log` DDL:

```sql
CREATE TABLE audit_log (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,
    entity_id UUID,
    brand_id UUID,
    org_id UUID,
    action TEXT NOT NULL,
    actor_id UUID,
    actor_type TEXT NOT NULL DEFAULT 'user',
    before_val JSONB,
    after_val JSONB,
    ip_address INET,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at)
```

followed by two child partitions (`audit_log_2025` FOR VALUES FROM `'2025-01-01'` TO `'2026-01-01'`; `audit_log_2026` FOR VALUES FROM `'2026-01-01'` TO `'2027-01-01'`), and the immutability block:

```sql
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omnibrand_app') THEN
        REVOKE UPDATE, DELETE ON audit_log FROM omnibrand_app;
        GRANT INSERT ON audit_log TO omnibrand_app;
    END IF;
END
$$;
```

There is a code comment at the top of the migration file stating explicitly: *"no `langgraph_checkpoints` table here by design — LangGraph's AsyncPostgresSaver manages its own checkpoint schema via `.setup()`, called during worker/API startup."*

### Why

- **FK-dependency creation order is mandatory, not stylistic**: PostgreSQL rejects `CREATE TABLE ... REFERENCES parent(id)` if `parent` doesn't exist yet — the ordering above (`orgs` → `brands` → `users` → everything else) is the topological sort of the actual foreign-key graph, not an arbitrary convention.
- **Dual-DSN (`ALEMBIC_DSN` vs `POSTGRES_DSN`)**: the `REVOKE UPDATE, DELETE ... FROM omnibrand_app` statement requires the executing role to *own* `audit_log` (or be superuser) — the app's own runtime credential (`POSTGRES_DSN`, used by `omnibrand_app` itself in a production topology with least-privilege roles) is exactly the role being revoked-from, so it cannot be the role that performs the revoke. `ALEMBIC_DSN` exists so migrations can run as a privileged/owner role distinct from the app's day-to-day runtime role.
- **`audit_log` partitioning by `created_at` range**: keeps the append-only audit table's indexes and vacuum/maintenance cost bounded per time-slice rather than growing one monolithic table indefinitely — a standard time-series partitioning pattern. Partitioned tables in PostgreSQL cannot carry FK constraints referencing them from child rows across partitions in the general case, and more directly here, **partitioned parent tables cannot themselves declare FK columns as target constraints in the way non-partitioned tables can bind cleanly across all partitions** — hence `entity_id`/`org_id`/`brand_id`/`actor_id` on `audit_log` are plain `UUID` columns, not FK-constrained, by deliberate design (documented inline in the migration).
- **Dropping `langgraph_checkpoints`**: the original spec called for a hand-authored `langgraph_checkpoints` table. `langgraph-checkpoint-postgres`'s `AsyncPostgresSaver` creates and owns its own schema (multiple tables: checkpoints, checkpoint writes, blobs) via its `.setup()` method — a hand-rolled table with that name would be entirely unused dead schema, since the saver never reads or writes to a table it didn't create itself. Removing it and calling `.setup()` at runtime (see `backend/worker/main.py`, §9) means the checkpoint schema is always in sync with whatever version of `langgraph-checkpoint-postgres` is actually installed, rather than a copy hand-maintained in a migration file that could drift from the library's real schema.
- **Conditional REVOKE/GRANT (`IF EXISTS ... omnibrand_app`)**: in local/dev environments there is typically one Postgres role (`omnibrand`) that both owns tables and runs the app — no separate `omnibrand_app` least-privilege role exists yet. Wrapping the REVOKE/GRANT in a role-existence check means the migration doesn't hard-fail in that common dev topology, while still being ready to enforce immutability the moment a real `omnibrand_app` role is introduced (e.g. in a production Terraform/IAM setup).

### Bug Found & Fix: missing audit_log catch-all partition

The original spec's migration created only a single `audit_log_2025` partition. Since the actual system date during this build is in 2026, any `INSERT INTO audit_log` would have failed immediately with `no partition of relation "audit_log" found for row`, because PostgreSQL range partitioning requires an exact matching partition for every row and has no implicit catch-all. Fix: added the `audit_log_2026` partition shown above so writes succeed for both years; the migration's downgrade correctly drops both (`DROP TABLE IF EXISTS audit_log_2026` before `audit_log_2025` before the parent `audit_log`).

### Implications

- **Verified table count**: `\dt` against a freshly migrated database shows 22 application tables plus Alembic's own `alembic_version` bookkeeping table (23 total) — no `langgraph_checkpoints` table, by design.
- **Verified partitioning**: `pg_class.relkind` for `audit_log` is `p` (partitioned table); `audit_log_2025`/`audit_log_2026` are ordinary (`r`) partitions with their own inherited indexes (`audit_log_2025_pkey`, `audit_log_2025_org_id_created_at_idx`, etc., auto-created per-partition by Postgres from the parent's index definitions).
- **Downgrade/upgrade round-trip verified**: `alembic downgrade base` followed by `alembic upgrade head` completes cleanly, confirming the `downgrade()` function's manual `DROP TABLE` ordering (reverse of creation order) is correct and doesn't leave orphaned FK-referencing tables.
- **Future-proofing gap**: the two hardcoded partitions mean a migration author must remember to add `audit_log_2027` (and beyond) in a future migration before 2027-01-01, or writes will start failing again — there is no automatic partition-management (e.g. `pg_partman`) wired in yet.
- **Least-privilege readiness**: the schema is already structurally ready for a real `omnibrand_app` role with restricted grants; introducing that role in a future migration will immediately activate the dormant REVOKE/GRANT logic without any schema changes.

---

## 6. Core Shared Contracts (`pipeline/state.py`, `pipeline/schemas.py`)

### What

`backend/pipeline/state.py` defines `OmniBrandState`, a `TypedDict` (not a Pydantic model — chosen for LangGraph compatibility, since LangGraph's `StateGraph` operates on plain dict-like state and uses `typing.get_type_hints`/`Annotated` metadata for reducer discovery), plus 10 supporting `TypedDict`s: `CampaignBrief`, `GenerationTask`, `ContentVariant`, `CriterionScore`, `BrandScore`, `AggregatedScore`, `ReviewRequest`, `PublicationReceipt`, `RAGContext`, `PriorCampaignContext`.

The state's accumulation fields, verbatim:

```python
    # Accumulated results (operator.add fan-in)
    variants: Annotated[list[ContentVariant], operator.add]
    brand_scores: Annotated[list[BrandScore], operator.add]
    aggregated_scores: Annotated[list[AggregatedScore], operator.add]
    review_requests: Annotated[list[ReviewRequest], operator.add]
    publication_receipts: Annotated[list[PublicationReceipt], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
```

All other fields (`campaign_id`, `brief`, `current_phase`, `token_cost_usd`, etc.) are plain, unannotated — meaning LangGraph's default merge behavior for them is "last write wins" within a single super-step, and **a hard error if more than one parallel branch attempts to write the same plain field in the same super-step** (see §9's fan-in bug).

`backend/pipeline/schemas.py` holds the Pydantic v2 (not TypedDict) request/response contracts, including the strict judge-output schema:

```python
class BrandScoreOutput(BaseModel):
    tone_alignment: CriterionScore
    vocabulary_compliance: CriterionScore
    channel_format_adherence: CriterionScore
    cta_style: CriterionScore
    cultural_appropriateness: CriterionScore
    factual_grounding: CriterionScore  # 6th criterion — weight 0.25
    composite_score: float = Field(..., ge=0.0, le=10.0)
    critical_violations: list[str] = Field(default_factory=list)
    routing_decision: Literal["auto_approve", "flag", "auto_reject"]
    routing_explanation: str = Field(..., min_length=20)
```

and a generic response envelope:

```python
T = TypeVar("T")

class ResponseEnvelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
```

`ReviewDecision` demonstrates cross-field validation via Pydantic v2's `@model_validator(mode="after")`:

```python
class ReviewDecision(BaseModel):
    decision: Literal["approved", "rejected", "edited"]
    reviewer_note: str | None = None
    edited_content: str | None = None

    @model_validator(mode="after")
    def check_edited_content_present(self) -> "ReviewDecision":
        if self.decision == "edited" and not self.edited_content:
            raise ValueError("edited_content is required when decision is 'edited'")
        if self.decision != "edited" and self.edited_content:
            raise ValueError("edited_content may only be set when decision is 'edited'")
        return self
```

### Why

- **TypedDict for `OmniBrandState`, Pydantic for `schemas.py`**: these serve different consumers. `OmniBrandState` is passed through `StateGraph` nodes as a plain dict at runtime (LangGraph internally does dict merges keyed by field name); wrapping it in a Pydantic `BaseModel` would add validation overhead on every node transition and complicate the `Annotated[..., operator.add]` reducer mechanism LangGraph specifically looks for. `schemas.py` models sit at the FastAPI request/response boundary, where Pydantic's validation, JSON (de)serialization, and OpenAPI schema generation are the actual point.
- **`operator.add` on exactly the 7 fields that are written by parallel branches**: `variants`/`brand_scores`/etc. are written by the 3 parallel judge nodes (`judge_claude`, `judge_gpt4o`, `judge_llama` all write `brand_scores`) or by nodes that may re-run (retries appending to `failed_task_ids`/`errors`). `operator.add` on a list field tells LangGraph "when two branches each return `{"brand_scores": [x]}` and `{"brand_scores": [y]}` in the same super-step, concatenate to `[x, y]`" instead of raising a conflict — this is what makes fan-out/fan-in across the 3 judges structurally sound (see §9 for what happens to fields that are *not* so annotated).
- **`BrandScoreOutput`'s exhaustive 6-criteria model with `ge=0.0, le=10.0` bounds and `min_length=20` on the explanation**: encodes the judge rubric's exact contract as an enforceable schema rather than a convention documented only in a prompt — any judge implementation returning malformed output fails Pydantic validation immediately rather than propagating a bad score silently into `aggregated_scores`.
- **`ResponseEnvelope[T]` as a `Generic`**: lets every API endpoint return the same `{data, meta}` shape while still getting concrete per-endpoint type checking (`ResponseEnvelope[CampaignResponse]` vs `ResponseEnvelope[list[VariantSummary]]`) rather than every handler hand-rolling its own envelope dict.

### Implications

- **Type safety boundary**: `mypy strict = true` (§3) applies to both files — every `TypedDict`/`BaseModel` field must be fully typed, and any agent code touching `OmniBrandState` gets static checking on which keys exist and their types, catching typos like `state["campain_id"]` at type-check time rather than at runtime `KeyError`.
- **Schema evolution risk**: because `OmniBrandState` is a `TypedDict`, adding/renaming a field requires updating every stub/agent function that constructs a literal state dict (e.g. `backend/worker/main.py`'s `_initial_state()` and `backend/tests/test_pipeline_skeleton.py`'s `_empty_state()`, both of which hand-list every field) — there is no `.model_construct()`-style partial-construction helper for `TypedDict`s the way Pydantic offers for `BaseModel`s.
- **Judge contract enforceability**: swapping `judge_claude_stub` etc. for a real LLM-backed implementation later can validate the raw LLM JSON output against `BrandScoreOutput` before writing to `brand_scores`, giving a hard boundary between "an LLM said something" and "the pipeline trusts a well-formed score."

---

## 7. Core Infrastructure Utilities (`backend/core/`)

### What

Six modules, each following the same **singleton + explicit init/close + health-check** pattern:

`backend/core/config.py` — Pydantic `BaseSettings` subclass, `env_file=".env"`, `extra="ignore"`. Full field list as currently implemented (RSA/JWT fields included, unmodified):

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme_app_secret_32chars_min"

    # Database
    POSTGRES_DSN: str = "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Vector store
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # LLM
    LITELLM_BASE_URL: str = "http://localhost:4000"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPL_API_KEY: str = ""

    # Auth
    JWT_PRIVATE_KEY_PATH: str = "./certs/private_key.pem"
    JWT_PUBLIC_KEY_PATH: str = "./certs/public_key.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Observability
    LANGFUSE_HOST: str = "http://localhost:3001"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    # Storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "omnibrand"
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "brand-assets"

    # Runtime
    MAX_CONCURRENT_CAMPAIGNS: int = 5
    CAMPAIGN_TIMEOUT_SECONDS: int = 300

    @property
    def private_key(self) -> str:
        with open(self.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()

    @property
    def public_key(self) -> str:
        with open(self.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()


settings = Settings()
```

`private_key`/`public_key` are `@property` methods that open and read the PEM file **on every access** (no caching) — every call to `create_access_token()`/`decode_access_token()` in `api/middleware/auth.py` (§8) performs a fresh disk read.

`backend/core/database.py`, `redis.py`, `qdrant.py` all share the identical shape: a module-level `_engine`/`_redis`/`_qdrant` variable initialized to `None`, an `async def init_x()` that constructs the real client and assigns the global, an `async def close_x()` that tears it down and resets to `None`, a sync `get_x()` that raises `RuntimeError` if called before `init_x()`, and an `async def check_x_health()` returning `bool` (never raising — wraps the real check in `try/except Exception: return False`).

`backend/core/metrics.py` defines a dedicated `CollectorRegistry()` (not the Prometheus client's global default registry) and four metrics: `llm_call_duration` (Histogram, labels `agent`/`model`/`task`), `llm_tokens_total` (Counter, labels `agent`/`model`/`type`), `campaign_duration` (Histogram, labels `org_id`/`status`), `campaign_cost_usd` (Histogram, labels `org_id`/`tier`).

`backend/core/langfuse.py` implements a `NullLangfuse` fallback class exposing the same method surface as the real `Langfuse` client (`trace`, `span`, `generation`, `update`, `end`, `flush`), all no-ops:

```python
def get_langfuse() -> Langfuse | NullLangfuse:
    global _client
    if _client is None:
        if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
            _client = NullLangfuse()
        else:
            try:
                _client = Langfuse(
                    host=settings.LANGFUSE_HOST,
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                )
            except Exception:
                _client = NullLangfuse()
    return _client
```

### Why

- **Module-global singleton instead of a dependency-injection container**: FastAPI's own `Depends()` system and the LangGraph worker loop are two different call environments — a DI container scoped to FastAPI wouldn't naturally serve the worker process. A plain module-level singleton, explicitly `init_x()`'d during `lifespan()` (API, §8) or inline at the top of `worker.main()` (§9), works identically in both contexts without extra plumbing.
- **`get_x()` raising `RuntimeError` rather than lazily initializing**: makes "you forgot to call `init_db()`" a loud, immediate, unambiguous crash at the first real usage rather than a silent `None`-related `AttributeError` deep in a query — the intent is fail-fast during development, not defensive lazy-init.
- **`check_x_health()` swallowing all exceptions**: this function's entire purpose is to be called from `/health` (§8) and report `up`/`down` — if it let exceptions propagate, a single unhealthy dependency would crash the health endpoint itself rather than reporting the degradation it exists to surface.
- **`NullLangfuse`**: `traced_llm_call()` (§9) calls `get_langfuse().trace(...)` unconditionally, with no `if langfuse_configured:` branch anywhere in the calling code — this is only possible because `NullLangfuse` guarantees the same method signatures return harmlessly. This directly supports the "no real LLM API keys required to run Phase 0" constraint: `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are empty strings in `.env.example`, so every environment boots into the null-object path by default, with zero code branching required at call sites.
- **Dedicated `CollectorRegistry()`** rather than Prometheus client's implicit global registry: avoids cross-contamination if this module is imported multiple times in different contexts (e.g. once by `api` process, once inside a test process importing the same module) — each explicit registry instance is independent.

### Implications

- **RSA file I/O on every JWT operation**: because `private_key`/`public_key` are uncached properties, every token issuance/verification does a filesystem `open()` — acceptable at Phase-0 traffic levels, but a caching layer (e.g. `functools.lru_cache` or reading once at `Settings()` construction time) would be a real optimization before this sees production JWT volume.
- **Process-local state**: because these are plain module-level globals (not e.g. a `contextvars.ContextVar`), each of the 4 Uvicorn workers spawned by `--workers 4` (§2) has its own independent `_engine`, meaning 4 separate connection pools to Postgres exist under one `api` process group — this is expected/correct for process-based concurrency, but means connection-pool sizing (`create_async_engine`'s default pool) must be considered per-worker, not per-container.
- **`NullLangfuse` masking misconfiguration**: if `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` are set to genuinely invalid values (not merely absent), the `except Exception: _client = NullLangfuse()` fallback silently swallows the real `Langfuse()` constructor's error and falls back to the null object — meaning a misconfigured (as opposed to unconfigured) Langfuse integration would fail silently rather than surfacing a startup error. This is a deliberate trade-off favoring availability over strict configuration validation.

---

## 8. FastAPI Application Layer

### What

`backend/api/main.py` — the entrypoint:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.database import close_db, init_db
    from core.qdrant import close_qdrant, init_qdrant
    from core.redis import close_redis, init_redis

    await init_db()
    await init_redis()
    await init_qdrant()
    yield
    await close_db()
    await close_redis()
    await close_qdrant()


app = FastAPI(
    title="OmniBrand Studio API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import auth, campaigns, health, knowledge, orgs  # noqa: E402

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(orgs.router, prefix="/orgs", tags=["orgs"])
app.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
```

Router imports are deliberately placed *after* `app`/middleware construction (hence the `# noqa: E402`, suppressing Ruff's "module level import not at top of file") — this is necessary because the router modules themselves import from `api.deps`/`api.middleware.auth`, which is fine at plain import time, but keeping app construction first and router wiring second makes the file read top-to-bottom as "build the app, then attach routes."

`backend/api/deps.py` — auth dependency layer, **current, unmodified, dual-path** implementation:

```python
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass
class UserContext:
    user_id: str
    org_id: str
    brand_ids: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    auth_method: str = "jwt"  # "jwt" | "api_key"


async def _authenticate_jwt(credentials: HTTPAuthorizationCredentials) -> UserContext:
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    jti = payload.get("jti")
    if jti and await is_jti_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")

    return UserContext(
        user_id=payload["sub"],
        org_id=payload["org_id"],
        brand_ids=payload.get("brand_ids", []),
        roles=payload.get("roles", []),
        auth_method="jwt",
    )


async def _authenticate_api_key(raw_key: str) -> UserContext:
    key_hash = hash_api_key(raw_key)
    async with get_db() as conn:
        result = await conn.exec_driver_sql(
            "SELECT org_id, brand_id, scopes FROM api_keys "
            "WHERE key_hash = %(key_hash)s AND revoked_at IS NULL "
            "AND (expires_at IS NULL OR expires_at > NOW())",
            {"key_hash": key_hash},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")

    return UserContext(
        user_id="api_key",
        org_id=str(row["org_id"]),
        brand_ids=[str(row["brand_id"])] if row["brand_id"] else [],
        roles=list(row["scopes"] or []),
        auth_method="api_key",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_header),
) -> UserContext:
    if credentials is not None:
        return await _authenticate_jwt(credentials)
    if api_key is not None:
        return await _authenticate_api_key(api_key)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")


def require(*permissions: str) -> Callable[[UserContext], UserContext]:
    def _check(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not set(permissions) & set(user.roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of: {', '.join(permissions)}",
            )
        return user

    return _check
```

`backend/api/middleware/auth.py` — the RSA/JWT + lockout implementation, **currently in place, unmodified**:

```python
def create_access_token(*, user_id: str, org_id: str, roles: list[str], brand_ids: list[str]) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "roles": roles,
        "brand_ids": brand_ids,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
    return jwt.encode(payload, settings.private_key, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.public_key, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


async def is_jti_revoked(jti: str) -> bool:
    redis = get_redis()
    return bool(await redis.exists(f"revoked_jti:{jti}"))


async def revoke_jti(jti: str, ttl_seconds: int) -> None:
    redis = get_redis()
    await redis.set(f"revoked_jti:{jti}", "1", ex=ttl_seconds)
```

plus account-lockout helpers (`is_locked_out`, `record_failed_login`, `clear_failed_logins`, keyed `lockout:{email}` in Redis, `LOCKOUT_MAX_ATTEMPTS = 5`, `LOCKOUT_WINDOW_SECONDS = 15 * 60`) and `hash_api_key()` (plain `hashlib.sha256`).

Router inventory — 5 routers registered, only `health` is functionally complete:

- `health.py` — `GET /health` (aggregates `check_db_health()` + `check_redis_health()` + `check_qdrant_health()` into `{"status": "healthy"|"degraded", "checks": {...}}`, where `overall_ok = db_ok and redis_ok` — Qdrant being down does **not** flip overall status to degraded, only Postgres/Redis do), `GET /health/live` (static `{"status": "alive"}`, no dependency checks — a true liveness probe), `GET /health/ready` (`db_ok and redis_ok` only, no Qdrant).
- `auth.py`, `campaigns.py`, `orgs.py`, `knowledge.py` — every handler in these four files is a one-line `raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "...")` stub. `auth.py` declares `POST /token`, `POST /refresh`, `POST /logout`; `campaigns.py` declares `POST ""`, `POST /{campaign_id}/run`, `GET /{campaign_id}`, `GET /{campaign_id}/status`; `orgs.py` declares `POST ""`, `GET /{org_id}`; `knowledge.py` declares `POST /brand-guides`, `GET /brand-guides/{brand_id}`.

`backend/services/audit_service.py` — `write_audit()`, the append-only audit writer with field scrubbing:

```python
SENSITIVE_FIELDS = {
    "password", "password_hash", "token", "key", "secret",
    "token_hash", "key_hash", "totp_secret_enc", "api_key",
}

def _scrub(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {k: ("***" if k in SENSITIVE_FIELDS else v) for k, v in value.items()}
```

`_scrub` does an **exact key-name match** against `SENSITIVE_FIELDS` (not substring/regex) on the top level of `before_val`/`after_val` only — nested dicts are not recursively scrubbed.

`backend/services/prompt_service.py` — `PromptService` with `CACHE_TTL = 60` (seconds), `get_active()` (org-specific-then-platform-fallback lookup, Redis-cached), `render()` (validates all `template.variables` are present in the caller-supplied `variables` dict before `.format()`-ing, raising `PromptVariableMissingError` otherwise), `record_performance()` (incremental rolling-average SQL `UPDATE` for `avg_brand_score`/`avg_latency_ms`/`approval_rate`).

### Why

- **Dual JWT/API-key auth in `get_current_user()`**: checked in that order (bearer credentials first, API key second) because `HTTPBearer(auto_error=False)`/`APIKeyHeader(auto_error=False)` both return `None` rather than raising when their respective header is absent — this lets one dependency function branch on whichever credential the caller actually supplied, supporting both a future human-user JWT flow and machine-to-machine API-key flow through the same `Depends(get_current_user)` call site in route handlers.
- **`jti` + Redis revocation set** rather than short-lived tokens alone: `ACCESS_TOKEN_EXPIRE_MINUTES = 15` bounds exposure but doesn't allow immediate logout — the `revoked_jti:{jti}` Redis key (checked via O(1) `EXISTS`) lets a specific already-issued token be invalidated before its natural expiry, which pure JWT expiry alone cannot do.
- **`write_audit()`'s exact-match-only scrubbing**: a conservative, predictable redaction rule — the trade-off is nested secrets (e.g. `{"user": {"password": "..."}}`) are not caught, but the set is easy to audit and extend, and top-level-only scrubbing is intentionally simple because `write_audit()`'s callers are expected to pass flat-ish before/after snapshots of specific entities (a `users` row, an `api_keys` row), not arbitrarily nested request bodies.
- **`PromptService`'s Redis cache with a short 60s TTL**: `prompt_registry` rows change rarely (an admin publishes a new active prompt version occasionally) but are read on every single agent invocation that calls `render()` — caching avoids a DB round-trip per LLM call while the short TTL bounds how long a newly-activated prompt takes to actually take effect across all callers (worst case 60 seconds of staleness, not indefinite).
- **Router stub pattern (`raise HTTPException(501, ...)`)**: makes "this endpoint is declared but not implemented" an explicit, discoverable, machine-readable state (visible in `/docs`, returns a real HTTP status) rather than the route simply not existing (404) — a client hitting a stub gets an unambiguous "not implemented yet," distinguishable from "this route doesn't exist at all."

### Implications

- **Auth surface today**: because no `/auth/token`-equivalent endpoint issues real JWTs yet (it's a 501 stub), `_authenticate_jwt()` is fully implemented and unit-testable but has no live issuance path in this codebase — the only auth mechanism actually exercisable end-to-end today is API-key (`_authenticate_api_key()`, which reads directly from the seeded/real `api_keys` table).
- **RBAC granularity**: `require(*permissions)` checks `set(permissions) & set(user.roles)` — any one matching role/scope grants access (OR semantics, not AND) — a route requiring `require("admin", "owner")` is satisfied by a user with either role, not both.
- **Verified live behavior**: `GET /health` was booted against real Postgres/Redis/Qdrant containers and returned `{"status":"healthy","checks":{"database":{"status":"up"},"redis":{"status":"up"},"qdrant":{"status":"up"}}}`; `/docs` returned HTTP 200 (OpenAPI UI renders, meaning every route including the 501 stubs is correctly registered and introspectable).
- **`overall_ok` excludes Qdrant**: a Qdrant outage will never flip `/health`'s top-level `status` to `"degraded"` — only its own `checks.qdrant.status` reflects the outage. Any external uptime monitor keying off the top-level `status` field alone would miss a Qdrant-only failure.
- **Prompt render safety**: `PromptVariableMissingError` is raised *before* any LLM call is attempted, so a caller with an incomplete variable set fails fast and cheaply rather than sending a malformed/partially-templated prompt to a paid LLM API.

---

## 9. LangGraph Pipeline & Worker

### What

`backend/pipeline/agents/base.py` — three functions plus one dict, `AGENT_WRITE_PERMISSIONS`, re-exported alongside `write_audit` (imported from `services/audit_service.py`) via `__all__`:

```python
__all__ = [
    "traced_llm_call",
    "write_audit",
    "safe_agent_run",
    "AGENT_WRITE_PERMISSIONS",
]
```

`traced_llm_call()` posts to LiteLLM's OpenAI-compatible `/chat/completions` endpoint via `httpx.AsyncClient`, wraps the call in a Langfuse trace (`get_langfuse().trace(...)`, unconditionally — see §7's `NullLangfuse`), records two Prometheus metrics (`llm_call_duration`, `llm_tokens_total`), and — only if `state.get("campaign_id")` is truthy — inserts a row into `campaign_cost_attribution` and commits. Returns `(content: str, usage_metadata: dict)`.

`safe_agent_run()` is the universal exception boundary for agent nodes:

```python
async def safe_agent_run(
    agent_fn: Callable[[OmniBrandState], Awaitable[dict]],
    state: OmniBrandState,
    task_id: str | None = None,
) -> dict:
    agent_name = getattr(agent_fn, "__name__", str(agent_fn))
    try:
        return await agent_fn(state)
    except Exception as exc:
        log.error("agent_failed", agent=agent_name, task_id=task_id, error=str(exc))
        error_msg = f"{agent_name} failed"
        if task_id:
            error_msg += f" (task_id={task_id})"
        error_msg += f": {exc}"
        result: dict = {"errors": [error_msg]}
        if task_id:
            result["failed_task_ids"] = [task_id]
        return result
```

Note: `safe_agent_run` is defined but **not currently wired into `build_graph()`** (§ below) — the graph registers the raw stub functions directly as nodes (`g.add_node("intake_agent", intake_agent_stub)`), not `safe_agent_run`-wrapped versions. It exists as the intended exception boundary for when real (LLM-calling, hence failure-prone) agent implementations replace the stubs.

`AGENT_WRITE_PERMISSIONS` maps each of the 10 real graph node names (not the `_stub`-suffixed function names) to the set of `OmniBrandState` keys that node is authorized to write:

```python
AGENT_WRITE_PERMISSIONS: dict[str, set[str]] = {
    "intake_agent": {"brief", "rag_context", "prior_campaigns", "brief_valid",
                      "brief_validation_errors", "budget_check_passed", "tasks",
                      "current_phase", "token_cost_usd", "errors"},
    "content_generator": {"variants", "failed_task_ids", "token_cost_usd",
                           "current_phase", "errors"},
    "personalization_agent": {"variants", "token_cost_usd", "errors"},
    "translation_agent": {"variants", "token_cost_usd", "errors"},
    "judge_claude": {"brand_scores", "token_cost_usd", "errors"},
    "judge_gpt4o": {"brand_scores", "token_cost_usd", "errors"},
    "judge_llama": {"brand_scores", "token_cost_usd", "errors"},
    "confidence_aggregator": {"aggregated_scores", "review_requests",
                               "human_review_requested"},
    "review_gate": {"variants", "current_phase"},
    "publishing_agent": {"publication_receipts", "variants", "current_phase", "errors"},
}
```

Note this dict still lists `token_cost_usd` as permitted for `judge_claude`/`judge_gpt4o`/`judge_llama` even though the actual stub implementations no longer write it (see the fan-in bug below) — the permission set is a maximum-allowed superset, not an assertion that every listed key is always written.

`backend/pipeline/agents/stubs.py` — 10 async agent stub functions plus one **synchronous** routing function, `reflexion_router_stub`. Each stub `structlog`-logs its own invocation (`log.info("agent_stub", agent="...", campaign_id=...)`) and returns a partial-state dict scoped to its own `AGENT_WRITE_PERMISSIONS` entry. The three judge stubs, after the fan-in fix (below), return only `{"brand_scores": []}` — no `token_cost_usd`. `reflexion_router_stub`:

```python
def reflexion_router_stub(state: OmniBrandState) -> str:
    log.info("agent_stub", agent="reflexion_router", campaign_id=state.get("campaign_id"))
    task_id = (state.get("current_task") or {}).get("task_id")
    if not task_id:
        return END
    variant = next((v for v in state["variants"] if v["task_id"] == task_id), None)
    if variant and variant.get("reflexion_applied") and variant.get("status") == "generated":
        return "validation_subgraph"
    return END
```

`backend/pipeline/graph.py` — `build_graph(checkpointer)` constructs the `StateGraph(OmniBrandState)`:

```python
g.set_entry_point("intake_agent")
g.add_edge("intake_agent", "content_generator")
g.add_edge("content_generator", "personalization_agent")
g.add_edge("personalization_agent", "translation_agent")
g.add_edge("translation_agent", "judge_claude")
g.add_edge("translation_agent", "judge_gpt4o")
g.add_edge("translation_agent", "judge_llama")
g.add_edge("judge_claude", "confidence_aggregator")
g.add_edge("judge_gpt4o", "confidence_aggregator")
g.add_edge("judge_llama", "confidence_aggregator")

g.add_conditional_edges(
    "confidence_aggregator",
    reflexion_router_stub,
    {"validation_subgraph": "judge_claude", END: "review_gate"},
)

g.add_edge("review_gate", "publishing_agent")
g.add_edge("publishing_agent", END)

return g.compile(
    checkpointer=checkpointer,
    interrupt_before=["review_gate"],
)
```

— i.e. linear `intake → content_generator → personalization → translation`, fan-out from `translation_agent` to all 3 judges in parallel, fan-in at `confidence_aggregator`, a conditional edge (either loop back to `judge_claude` for re-scoring, or proceed to `review_gate`), then `review_gate → publishing_agent → END`. `interrupt_before=["review_gate"]` means `graph.ainvoke()` returns control to the caller *before* executing `review_gate` — this is the deliberate human-in-the-loop pause point; the worker currently never resumes past it (no resume-after-interrupt code exists yet in `worker/main.py`).

### Bug Found & Fix: judge stub fan-in conflict on `token_cost_usd`

Initial implementation had all three judge stubs return `{"brand_scores": [], "token_cost_usd": 0.0}`. Running the pipeline produced:

```
error="At key 'token_cost_usd': Can receive only one value per step.
Use an Annotated key to handle multiple values."
```

Root cause: `token_cost_usd` on `OmniBrandState` (§6) is a plain `float`, not `Annotated[..., operator.add]` — when `judge_claude`, `judge_gpt4o`, and `judge_llama` execute in the same LangGraph super-step (true parallel fan-out) and all three attempt to write the same non-fan-in key, LangGraph has no merge strategy and raises. Fix: removed `token_cost_usd` from all three judge stub return dicts (shown in the stub excerpt above) — the comment left in place states real judge implementations should route cost recording through `campaign_cost_attribution` via `traced_llm_call()` instead of the in-memory state field, which sidesteps the conflict entirely since that's a DB insert, not a state-merge.

`backend/worker/main.py` — the Redis consumer:

```python
QUEUE = "campaigns:queue"
DLQ = "campaigns:dead_letter"

async def process_campaign(task_payload: dict) -> None:
    campaign_id = task_payload["campaign_id"]
    initial_state = _initial_state(task_payload)

    psycopg_dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = {"configurable": {"thread_id": campaign_id}}
        await graph.ainvoke(initial_state, config=config)


async def main() -> None:
    await init_redis()
    redis = get_redis()
    log.info("worker_started", queue=QUEUE)
    try:
        while True:
            item = await redis.blpop(QUEUE, timeout=5)
            if item is None:
                continue
            _, payload = item
            task = json.loads(payload)
            try:
                await process_campaign(task)
                log.info("campaign_processed", campaign_id=task.get("campaign_id"))
            except Exception as exc:
                log.error("campaign_failed", campaign_id=task.get("campaign_id"), error=str(exc))
                await redis.rpush(DLQ, json.dumps({**task, "error": str(exc)}))
    finally:
        await close_redis()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
```

### Bug Found & Fix: psycopg DSN driver suffix

`AsyncPostgresSaver.from_conn_string()` (from `langgraph-checkpoint-postgres`) uses `psycopg` directly, which does not understand SQLAlchemy's `+asyncpg` driver-suffix convention in a DSN. Passing `settings.POSTGRES_DSN` (`postgresql+asyncpg://...`) verbatim produced `missing "=" after "postgresql+asyncpg://..." in connection info string`. Fix: `psycopg_dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")` before constructing the saver — this same one-line fix is duplicated in `backend/tests/test_pipeline_skeleton.py` and `scripts/smoke_test.py`, since both also construct an `AsyncPostgresSaver` directly.

### Bug Found & Fix: psycopg async mode vs. Windows ProactorEventLoop

`psycopg`'s async connection mode (used internally by `AsyncPostgresSaver`) raises `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode` under Windows' default asyncio event loop policy. Fix: both `worker/main.py`'s `if __name__ == "__main__":` block and `backend/tests/conftest.py` explicitly set `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` before any event loop is created, conditioned on `sys.platform == "win32"`.

### Bug Found & Fix: Redis BLPOP indefinite timeout

The original implementation used `await redis.blpop(QUEUE, timeout=0)` (block forever, standard Redis semantics for `timeout=0`). This raised `redis.exceptions.TimeoutError: Timeout reading from localhost:6379` because redis-py's client-side socket timeout is independent of and shorter than an indefinite server-side block. Fix: changed to `await redis.blpop(QUEUE, timeout=5)` (poll every 5 seconds, `continue` the `while True` loop on `None`) and set an explicit `socket_timeout=10` on the Redis client in `core/redis.py`'s `init_redis()` (must exceed the longest blocking call).

### Why

- **`AGENT_WRITE_PERMISSIONS` as a runtime-checkable dict, not just documentation**: `backend/tests/test_pipeline_skeleton.py`'s `test_agent_write_permissions` actually asserts every stub's returned keys are a subset of its declared permission set — this turns "which fields can this agent touch" from a comment convention into an enforced invariant with a failing test if violated.
- **`interrupt_before=["review_gate"]`**: encodes the human-in-the-loop requirement structurally in the graph definition itself (LangGraph's checkpoint-aware interrupt mechanism) rather than as an if-statement inside a node — the graph *cannot* proceed past `review_gate` without an explicit external resume call against the saved checkpoint, which is the correct mechanical guarantee for "a human must approve before publishing."
- **Judges as three separate parallel nodes rather than one node calling three models sequentially**: this is what makes multi-judge consensus latency-bound by the *slowest* judge rather than the *sum* of all three — the fan-out/fan-in graph shape is a deliberate concurrency choice, not just a stylistic preference for more nodes.
- **`safe_agent_run` defined ahead of need**: written now, unused by the graph today, so that the transition from stub to real (LLM-calling, network-fallible) agents later is a one-line wrap (`g.add_node("judge_claude", lambda s: safe_agent_run(judge_claude_real, s))`-style) rather than requiring every future agent implementation to hand-roll its own try/except.

### Implications

- **Verified end-to-end behavior**: a smoke run (enqueue a task payload onto `campaigns:queue`, `worker.main` consuming it) produced 8 LangGraph checkpoints for the thread and left the dead-letter queue empty — confirming intake → content_generator → personalization → translation → all 3 judges → confidence_aggregator → reflexion_router → correctly halts at the `review_gate` interrupt (never reaching `publishing_agent`, as designed, since nothing resumes the interrupted run yet).
- **No resume-past-interrupt path exists yet**: `graph.ainvoke()` returning after hitting `interrupt_before` is the full extent of current worker behavior — a future `/campaigns/{id}/review` endpoint (or equivalent) must call `graph.ainvoke(None, config=...)` (LangGraph's resume convention: passing `None` as input continues from the last checkpoint) to actually reach `publishing_agent`.
- **DLQ has no consumer/retry logic**: `worker/main.py` pushes failed tasks to `campaigns:dead_letter` but nothing in the codebase currently reads from that list — it accumulates until manually inspected.
- **Cost tracking split across two mechanisms**: `token_cost_usd` on `OmniBrandState` (a running total intended for cheap synchronous nodes) versus `campaign_cost_attribution` (a durable per-LLM-call audit trail written by `traced_llm_call`) are two different cost-tracking surfaces that must eventually be reconciled by whatever aggregates final campaign cost — they are not currently kept in sync by any code.

---

## 10. Testing & Verification Tooling

### What

`backend/tests/conftest.py` — 7 lines, sole purpose is the Windows event-loop-policy fix described in §9, applied once per test session at collection time (module-level code, runs on import).

`backend/tests/test_pipeline_skeleton.py` — 5 tests:

- `test_all_stubs_are_coroutines` — asserts all 10 agent stub functions (by name, from a hardcoded `AGENT_STUB_NAMES` list) are `asyncio.iscoroutinefunction`.
- `test_reflexion_router_is_sync` — asserts the opposite for `reflexion_router_stub`: not a coroutine function, and `inspect.isfunction` (a plain function, distinguishing it from the async agent nodes).
- `test_agent_write_permissions` — builds a `node_to_stub` dict mapping the 10 real node names to their stub functions, asserts its key set exactly equals `AGENT_WRITE_PERMISSIONS.keys()`, then actually invokes every stub against a synthetic empty state and asserts each returned dict's keys are a subset of that node's permitted set.
- `test_reflexion_router_returns_valid_label` — calls `reflexion_router_stub` directly with two constructed states: one with `current_task=None` (asserts `END`), one with a matching variant that has `reflexion_applied=True` and `status="generated"` (asserts `"validation_subgraph"`).
- `test_fan_out_fan_in_accumulation` — constructs a real `AsyncPostgresSaver` against the live `POSTGRES_DSN` (with the `+asyncpg` suffix stripped), calls `checkpointer.setup()`, builds the graph, and asserts the compiled graph's node set is a superset of the 12 expected node names (10 agents + `__start__`/`__end__`).

All 5 tests pass against a live Postgres instance (verified — `5 passed in 1.97s`).

`scripts/seed_prompts.py` — idempotent seed script (importable as a standalone script, inserts `sys.path` entry for `backend/` manually since it's outside the package). Seeds exactly 7 `prompt_registry` rows (6 channel-generation prompts for `email`, `sms`, `social_post`, `display_ad`, `landing_page`, `push_notification`, plus 1 `judge_rubric` prompt) via `ON CONFLICT (name, version, org_id) DO UPDATE`, one `orgs` row (`Test Org` / slug `test-org`, hardcoded UUID `00000000-0000-0000-0000-000000000001`) and one `brands` row (`Test Brand`, hardcoded UUID `...002`) via `ON CONFLICT DO NOTHING`, and re-applies the same conditional `audit_log` REVOKE/GRANT block found in the migration (belt-and-suspenders in case a role is added after the initial migration ran).

`scripts/smoke_test.py` — end-to-end verification with explicit lite/full
modes. It inserts valid `campaigns` rows before enqueuing worker payloads,
polls persisted campaign status, checks only matching dead-letter entries, and
accepts `published` or the intentional `awaiting_review` pause. Lite mode keeps
API health and application `/metrics` checks while skipping external
observability. Full mode additionally validates Prometheus, Grafana, Jaeger,
targets, rules, and metric series. `--require-publishing` makes MailHog delivery
mandatory for a strict CP4 run.

`scripts/generate_certs.sh` / `scripts/generate_certs.ps1` — RSA keypair generation, both idempotent (skip if `certs/private_key.pem` already exists). The bash version shells out to `openssl genrsa`/`openssl rsa -pubout`. The PowerShell version prefers `openssl` if found on `PATH`, otherwise falls back to a temp Python script using `cryptography.hazmat.primitives.asymmetric.rsa` (2048-bit key, PKCS8 private / SubjectPublicKeyInfo public PEM encoding), invoked via `uv run python`.

### Why

- **`test_agent_write_permissions` invoking real stub functions rather than static-analyzing them**: guarantees the test fails the moment any stub is edited to return an unauthorized key, regardless of how the violation was introduced — a purely static check (e.g. grepping return statements) would be far more brittle to refactors.
- **`test_fan_out_fan_in_accumulation` asserting node *names* rather than running the graph to completion**: this test's actual job is to prove `build_graph()` compiles without raising and produces the expected topology — it deliberately does not exercise the fan-in `operator.add` behavior at runtime (that's covered by the smoke test's live worker run instead), keeping the pytest suite fast and independent of the worker/Redis being up.
- **`scripts/smoke_test.py` enqueuing directly after persistence**: this
  exercises the worker's real queue contract while preserving the database
  lifecycle the API normally establishes. Polling the database avoids the old
  false positive where an empty Redis queue merely meant the worker had
  dequeued a still-running campaign.
- **Idempotent cert/seed scripts**: both are designed to be safely re-run as part of `make setup` on a machine that's already been set up once, without regenerating keys (which would invalidate any already-issued tokens) or duplicating seed rows.

### Implications

- **Test suite currently has zero coverage of `api/deps.py`, `api/middleware/auth.py`, or any router** — the entire `backend/tests/` directory is pipeline/graph-focused; no test exercises `_authenticate_jwt`, `_authenticate_api_key`, `require()`, `write_audit`, or `PromptService` today.
- **`test-unit`/`test-integration` Makefile targets reference non-existent directories** (§1) — running `make test-unit` today would fail with a pytest "no tests collected" or path error, since `backend/tests/unit/` doesn't exist; this is forward-declared structure, not yet backed by files.
- **Smoke test's 60-second timeout and 5-checkpoint threshold are hardcoded** (`TIMEOUT_SECONDS = 60`, `checkpoint_count > 5`) — as real (non-stub) agents are added and per-node latency increases (real LLM calls take seconds, not milliseconds), this timeout will need to grow, and the "more than 5 checkpoints" threshold was chosen empirically against the current 10-stub-node topology (verified to produce exactly 8 checkpoints in a real run) rather than derived from a formula.
