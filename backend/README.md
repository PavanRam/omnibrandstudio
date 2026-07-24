# Backend Guide

The backend contains the API, worker, orchestration pipeline, services,
database migrations, and backend tests.

## Main Areas

| Path | Purpose |
| --- | --- |
| `api/` | FastAPI app, routers, middleware, auth, dependencies |
| `pipeline/` | LangGraph state, graph wiring, agent implementations |
| `services/` | Domain services for prompts, reviews, campaigns, chat, audit, and brand logic |
| `worker/` | Background queue consumer that executes campaign runs |
| `alembic/` | Database migration history |
| `tests/` | Unit and integration tests |
| `core/` | Shared runtime config, metrics, tracing, database, Redis |

## Key Entry Points

| File | Why it matters |
| --- | --- |
| `api/main.py` | FastAPI app startup and lifespan wiring |
| `pipeline/graph.py` | LangGraph assembly and execution graph |
| `pipeline/state.py` | Shared pipeline state contract |
| `pipeline/agents/base.py` | Shared agent safety, tracing, and write permissions |
| `worker/main.py` | Queue consumer runtime |
| `core/metrics.py` | Prometheus metrics definitions |

## Useful Commands

```bash
make run
make worker
make dev
make test
make lint
make migrate
make seed
```

## Working Notes

- Use `uv run` for Python commands.
- Prefer `make dev` for backend-only local development.
- The worker is required for full campaign execution; API-only startup is not enough for end-to-end validation.
