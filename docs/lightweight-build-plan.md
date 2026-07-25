# Making OmniBrand Studio Lightweight

Findings and a concrete action plan for reducing local build size, image weight,
and runtime memory/CPU footprint — without losing the real agent pipeline, the
UI, real LLM calls, or key functional flows (e.g. email publishing).

This document was produced from a live debugging session (2026-07-24/25) that
started as a Postgres auth failure and expanded into a full audit of what's
actually heavy in this repo and why.

---

## 0. Implementation-readiness review (2026-07-25)

**Status: directionally sound, but not yet execution-ready as originally
written.** The dependency and Compose reductions are valid, but the embedding
migration, lite/full OTel behavior, and acceptance criteria need to be made
explicit before implementation.

### 0.1 Hosted embeddings need a dedicated traced call

`traced_llm_call()` currently posts only to `/chat/completions` and parses a
chat-completion response. It cannot be reused as-is for embeddings. Implement a
dedicated traced embedding function that:

- posts batched input to LiteLLM's `/embeddings` endpoint using the `embedding`
  model alias;
- records latency, model resolution, usage/cost, Langfuse metadata, and OTel
  spans consistently with `traced_llm_call()`;
- returns vectors in input order; and
- falls back only on a controlled, logged embedding failure.

This preserves the architectural intent that model traffic goes through
LiteLLM without forcing an embedding response through the chat-completion
contract.

### 0.2 Embedding dimensions and persisted indexes must be migrated

The current `all-MiniLM-L6-v2` and hash fallback produce 384-dimensional
vectors. `text-embedding-3-small` defaults to 1536 dimensions. Chroma
collections and Pinecone indexes cannot safely mix vectors from the old and new
embedding spaces, even if the hosted model is configured to emit 384
dimensions.

Before switching providers:

1. Choose and configure one canonical embedding dimension.
2. Make the deterministic fallback emit that same dimension.
3. Re-embed/re-index all retained Chroma and Pinecone content.
4. Add a clear local reset/re-index command or documented migration procedure.
5. Never silently delete persisted vector data; require an explicit operator
   action for destructive local resets.

The current workspace contains persisted local Chroma data, so this is an
active migration concern rather than a theoretical one.

### 0.3 Current credentials would degrade RAG to hash embeddings

The current local `.env` has `GROQ_API_KEY` configured but
`OPENAI_API_KEY` empty. The proposed `embedding` alias resolves to OpenAI, so
the hosted call cannot succeed in the current environment. Making the hash
fallback primary in practice would keep code running, but it would materially
degrade semantic retrieval and therefore does not support the claim of "no
functionality loss."

A product/runtime decision is required:

- **Hosted-semantic option:** require a valid provider key for the `embedding`
  alias and treat the deterministic hash vector as an explicit degraded mode;
  or
- **Offline-semantic option:** select a genuinely lightweight local semantic
  embedding implementation and account for its image/runtime cost.

Do not describe hash-only retrieval as functionally equivalent to semantic
embeddings.

### 0.4 Lite/full Compose behavior needs exact defaults

Use explicit profiles and environment defaults:

- default/unprofiled: `postgres`, `redis`, `litellm`, `mailhog`, `api`,
  `worker`;
- `observability`: `langfuse`, `prometheus`, `grafana`, `jaeger`,
  `redis-exporter`, `postgres-exporter`;
- `storage`: `minio`, `createbuckets`.

Set `OTEL_ENABLED=${OTEL_ENABLED:-0}` for the default stack. The full-stack Make
target must enable the observability profile and set `OTEL_ENABLED=1`; otherwise
either lite mode produces Jaeger retry noise or full mode starts Jaeger without
emitting traces.

### 0.5 Verification must prove the key flow, not only queue drainage

The current smoke script considers a campaign processed once the Redis queue is
empty. A worker can dequeue a campaign before the pipeline finishes or fails,
so queue drainage alone does not prove successful completion, human-review
behavior, or email publishing.

The lite acceptance gate should:

- keep API health and the application's own `/metrics` check;
- skip or soft-warn only on external Prometheus, Grafana, and Jaeger checks;
- wait for a terminal campaign/checkpoint status rather than only queue depth;
- fail on a matching dead-letter/error outcome; and
- verify the required publishing receipt or MailHog delivery for the CP4 flow.

Add focused tests for hosted embedding response parsing, fallback behavior,
dimension consistency, TF-IDF reranking, and lite/full smoke selection.

### 0.6 Documentation and worktree scope

In addition to `docs/setup.md` and `docs/run-and-operations-guide.md`, update
`README.md` and `docs/implementation-deep-dive.md`, which currently describe
MinIO/observability as default services and Presidio as an installed
dependency.

The repository already has unrelated uncommitted documentation and lockfile
changes. Implementation must preserve those edits. In particular, regenerating
`uv.lock` must retain the existing `aiosmtplib` update and avoid treating the
current lockfile diff as disposable generated noise.

---

## 1. Background — what triggered this

`make migrate-docker` failed with `asyncpg.exceptions.InvalidPasswordError`.
Root cause: the `omnibrandstudio_postgres_data` Docker volume had already been
initialized (from an earlier run) with a different password than the current
`.env`. Postgres only applies `POSTGRES_PASSWORD` on first init of an *empty*
data directory — changing `.env` later has no effect until the volume is reset.

Fixing that led to two further, independent problems:

1. **Docker Desktop's VM disk was capped (~58GB) and nearly full** — every
   `docker compose build` regenerates large dependency layers and build cache,
   and repeated builds hit `no space left on device` mid-build. This is a
   *virtual disk* limit, unrelated to the host Mac's actual free space
   (~430GB free at the time).
2. **The `api`/`worker` images were heavy (~14GB) and slow to build**, mostly
   due to `torch`/`transformers`/`triton` pulled in transitively by
   `sentence-transformers`.

Both problems compound: big images → big build cache → disk fills → builds
fail → more retries → more cache. This doc covers the fix for both the image
weight and the runtime container count.

---

## 2. Analysis — where the weight actually comes from

### 2.1 Image bloat (build time, disk, and image size)

Checked `pyproject.toml` dependencies against actual usage in `backend/`:

| Dependency | Pulls in | Actual usage | Verdict |
|---|---|---|---|
| `sentence-transformers` | `torch` (~3-4GB), `transformers` (~2GB), `triton` | [`services/rag/embeddings.py`](../backend/services/rag/embeddings.py) — wrapped in `try/except ImportError`, **already falls back to a deterministic hash embedding** when unavailable | Safe to drop as a hard dependency — the fallback path already exists in code |
| `sentence-transformers` (`CrossEncoder`) | (same torch/transformers) | [`services/rag/reranker.py`](../backend/services/rag/reranker.py) — wrapped in `try/except`, **already falls back to `TFIDFReranker`** (scikit-learn TF-IDF + cosine similarity) | Same — fallback already exists |
| `presidio-analyzer` / `presidio-anonymizer` | spaCy + language models | **Zero references found anywhere in `backend/`** (confirmed via repo-wide grep) | Dead dependency — remove entirely, no functionality lost |
| `sacrebleu` | numpy, portalocker (moderate) | [`pipeline/agents/translation.py`](../backend/pipeline/agents/translation.py) — actually used for translation quality scoring | Keep |
| `scikit-learn`, `nltk` | moderate | Used by `TFIDFReranker` and `hybrid.py` (stopwords) | Keep |

**Architectural note:** the project's own model-alias design
(`CLAUDE.md` → `embedding` alias → `text-embedding-3-small` via LiteLLM)
already intends embeddings to go through the hosted LiteLLM proxy, not a
local torch model. `embeddings.py` currently bypasses that pattern by loading
`sentence-transformers` locally instead. Making the hash-embedding /
LiteLLM-based path primary (instead of a fallback-only path) removes the
`torch`/`transformers`/`triton` stack from the image entirely — the single
biggest win, ~5-6GB.

### 2.2 Runtime container footprint (RAM, restart time)

`docker-compose.yml` starts **13 services** for `make up`. Not all of them are
needed for "main agents + key flow + UI" to work:

| Service | Required for core flow? | Reasoning |
|---|---|---|
| `postgres` | **Yes** | primary DB + LangGraph checkpoints |
| `redis` | **Yes** | campaign queue (BLPOP), LiteLLM cache, JWT jti revocation, login lockout, prompt cache |
| `litellm` | **Yes** | every LLM call goes through it (`traced_llm_call` → `httpx` → `LITELLM_BASE_URL`) |
| `api`, `worker` | **Yes** | the application itself |
| `mailhog` | **Yes** — initially miscategorized as "observability," corrected after re-check | [`pipeline/agents/publishing.py:140`](../backend/pipeline/agents/publishing.py#L140) sends real SMTP via `aiosmtplib` to `settings.PUBLISH_SMTP_HOST` (default `"mailhog"`, port 1025) — this is the actual delivery mechanism for CP4 ("Approved content publishes to LinkedIn + Email"), not tooling |
| `minio`, `createbuckets` | **No** | `S3_ENDPOINT_URL`/`S3_BUCKET` are declared in `core/config.py` but have **zero consumers** anywhere in `backend/` (confirmed via grep) — dead config, no agent reads or writes to it |
| `langfuse` | **No** | Has a real no-op fallback: [`core/langfuse.py:73-94`](../backend/core/langfuse.py#L73) returns `NullLangfuse()` whenever `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are blank (the default) — safe to drop regardless of whether the langfuse host is reachable |
| `prometheus`, `grafana` | **No** | `prometheus_client` in `api`/`worker` only *exposes* a local `/metrics` HTTP endpoint for an external Prometheus to scrape — it never connects outward, so no code path breaks without them |
| `jaeger` | **No**, with one caveat | OTel span export ([`core/tracing.py`](../backend/core/tracing.py)) uses `BatchSpanProcessor`, which exports asynchronously and swallows failures — won't crash or block requests. **But** `OTEL_ENABLED` defaults to `True` ([`core/config.py:87`](../backend/core/config.py#L87)), so without also disabling it, api/worker will continuously retry an OTLP connection to a `jaeger` hostname that no longer resolves — background noise, not a functional break |
| `redis-exporter`, `postgres-exporter` | **No** | pure Prometheus scrape targets, nothing in app code talks to them |

**Compose-level dependency check:** `depends_on` for `api` and `worker` only
requires `postgres` + `redis` to be healthy — dropping the other containers
does not block container startup at the Docker Compose level.

**Startup/lifespan check:** read both `api/main.py`'s `lifespan()` and
`worker/main.py`'s `main()` in full — both only call `init_db()` (postgres)
and `init_redis()` (redis) at startup. No eager connection to litellm, minio,
langfuse, or jaeger at boot in either process. `litellm` connections are
lazy, opened per-call inside `traced_llm_call`.

**Frontend check:** `frontend/src` has zero references to the ports used by
grafana/prometheus/jaeger/mailhog/minio — no UI dependency on any of the
dropped services.

### 2.3 A note on `local-eval` mode (considered, not chosen for this)

`docs/local-eval-developer-guide.md` documents an existing no-Docker shortcut
(`POST /eval/local-eval`, gated by `ENABLE_LOCAL_EVAL=true` +
`APP_ENV != production`) that runs the LangGraph pipeline in-process,
synchronously, with no queue/worker/UI wiring at all. It's useful for fast
agent-logic iteration, but it bypasses the queue, the worker, and all
UI-facing SSE/WebSocket events — not a fit for "UI + key flow works, just
lighter." Extending it to cover UI/E2E would mean duplicating the worker's
event-emission logic inside the API process, creating two pipeline code paths
that can drift apart (exactly what its own `TEMP_LOCAL_EVAL` tagging is meant
to flag for eventual removal). Decision: leave `local-eval` as-is for its
intended purpose; make the *real* path lighter instead (this doc).

---

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Drop `sentence-transformers` (and transitively `torch`/`transformers`/`triton`) as a hard dependency; promote the existing hash-embedding and `TFIDFReranker` fallback paths to primary, routed through the `embedding` LiteLLM alias for real embeddings | Fallbacks already exist in code; this is the single largest image-size win (~5-6GB) with no loss of functionality |
| 2 | Remove `presidio-analyzer` / `presidio-anonymizer` entirely | Zero usage anywhere in the codebase |
| 3 | Split `docker-compose.yml` services into a default ("lite") set and an opt-in `observability` profile | UI/queue/worker/real-LLM-calls/email-publishing all keep working; only unused-by-app-code tooling is deferred |
| 4 | Keep `mailhog` in the default set | It's load-bearing for the publishing agent, not observability — corrected after initial miscategorization |
| 5 | Keep `postgres`, `redis`, `litellm` in the default set | Required by core invariants (state persistence, queue, all LLM calls) |
| 6 | Drop `minio`/`createbuckets` from the default set | Declared config, zero code consumers |
| 7 | When running the lite profile, explicitly set `OTEL_ENABLED=0` | Default is `True`; without jaeger, this causes background OTLP retry noise (non-fatal, but wasteful and confusing in logs) |
| 8 | Patch `scripts/smoke_test.py` to accept a lite-mode flag | It currently hardcodes prometheus/grafana/jaeger checks as required; these would false-fail in lite mode even though the actual pipeline works fine |
| 9 | Periodically run `docker builder prune -af` | Build cache (not final images) was the dominant contributor to the Docker Desktop VM disk filling up (~20-38GB reclaimed each time in this session) |

---

## 4. Action items (not yet implemented — pending go-ahead)

- [ ] Remove `presidio-analyzer`, `presidio-anonymizer` from `pyproject.toml` (+ `uv lock`)
- [ ] Remove `sentence-transformers` from `pyproject.toml`; update `embeddings.py` to call the `embedding` LiteLLM alias (via `traced_llm_call`, per invariant #2 in `CLAUDE.md`) as primary, hash-embedding as last-resort fallback
- [ ] Update `reranker.py` to use `TFIDFReranker` as primary; drop the `CrossEncoder`/sentence-transformers path
- [ ] Add `profiles: ["observability"]` to `langfuse`, `prometheus`, `grafana`, `jaeger`, `redis-exporter`, `postgres-exporter` in `docker-compose.yml`; remove `minio`/`createbuckets` from the default `make up` service list (or also gate behind a profile if still wanted occasionally)
- [ ] Add `OTEL_ENABLED: 0` to `api`/`worker` environment when running without the `observability` profile (e.g. a `docker-compose.override.yml` or a documented env var toggle)
- [ ] Add `make up-full` (or `make up --profile observability`) target for when dashboards/tracing/langfuse are actually needed
- [ ] Update `docs/setup.md` / `docs/run-and-operations-guide.md` service tables to reflect default vs. opt-in services
- [ ] Patch `scripts/smoke_test.py` with a `--lite` flag (or env-based detection) that skips/soft-warns on prometheus/grafana/jaeger checks instead of failing the gate
- [ ] Rebuild `api`/`worker` images and confirm size reduction + `make smoke` (lite-aware) passes

---

## 5. Verification already performed (this session)

- Repo-wide grep confirmed no remaining code references to `presidio` anywhere in `backend/`.
- Repo-wide grep confirmed `S3_ENDPOINT_URL`/`S3_BUCKET`/`boto3` have no consumers outside `core/config.py`'s declaration.
- Read `embeddings.py` and `reranker.py` in full — confirmed working, already-wired fallback paths for both.
- Read `docker-compose.yml` `depends_on` blocks for `api`/`worker` — only `postgres` + `redis` required at the compose level.
- Read `api/main.py` `lifespan()` and `worker/main.py` `main()` in full — confirmed no eager connections to litellm/minio/langfuse/jaeger at process startup.
- Read `core/langfuse.py` in full — confirmed `NullLangfuse` fallback triggers on blank keys (the default), independent of host reachability.
- Read `core/tracing.py` in full — confirmed OTel setup is gated by `OTEL_ENABLED` and, when enabled, exports asynchronously without blocking or crashing on unreachable endpoints.
- Confirmed `OTEL_ENABLED` defaults to `True` in `core/config.py` — this is the one setting that needs an explicit override in lite mode, otherwise harmless but noisy.
- Grepped `frontend/src` for observability service ports — no UI dependency found.
- Confirmed via `docker system df` that build cache (15-38GB across two prune events) was the dominant disk consumer versus final images or volumes.

---

## 6. Related repo-wide Docker/Postgres notes (from the same session, adjacent issue)

- The `omnibrandstudio_postgres_data` volume persists independently of `.env`
  changes. If `POSTGRES_PASSWORD` is changed but auth still fails, check
  `docker volume ls` for a pre-existing `*_postgres_data` volume before
  assuming `.env` is misconfigured — Postgres only applies the password env
  var on first init of an empty data directory.
- Resetting that volume destroys local dev data (campaigns, brands,
  audit_log, checkpoints, prompt_registry, etc.) — it is **not** empty
  scaffolding by default in this repo; confirm with whoever owns the data
  before wiping.
- `backend/Dockerfile` build context is the repo root (`context: .` in
  `docker-compose.yml`), not `backend/` — `pyproject.toml`/`uv.lock` at the
  repo root are what's copied into the image.
- When piping `docker compose build` through `| tail -N`, the reported exit
  code reflects `tail`, not the build — a failed build (e.g. mid-`COPY`
  disk-space error) can be misread as a successful one. Check build output
  directly for `ERROR` lines, don't trust a piped exit code.
