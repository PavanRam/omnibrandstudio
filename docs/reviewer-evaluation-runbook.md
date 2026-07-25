# Reviewer Evaluation Runbook

Use this guide to start OmniBrand Studio locally for review and evaluation.

## Prerequisites

- Docker Desktop is running
- `.env` exists at the repository root and contains the required values
- `uv` is installed
- Run all commands from the repository root

## First-Time Startup

Use this path on a brand-new machine or the first time you run the project:

```bash
make fresh-start
make smoke
make urls
```

What this does:

- `make fresh-start` installs Python dependencies, generates JWT keys, and starts the Docker stack
- `make smoke` runs the end-to-end acceptance check
- `make urls` prints the local URLs and credentials for the running services

## Returning Reviewer Startup

Use this path if the project has already been run before and you just want to stop and restart the stack cleanly:

```bash
make restart
make urls
```

## Services To Open

After startup, use:

```bash
make urls
```

That prints the local addresses for:

- App API / Swagger docs
- Grafana
- Prometheus
- Jaeger
- Langfuse
- MinIO
- Mailhog

## Useful Evaluation Commands

```bash
make logs
make smoke
make test
```

- `make logs` tails API and worker logs
- `make smoke` reruns the end-to-end validation flow
- `make test` runs the backend test suite

## Stop The Environment

Stop containers but keep data:

```bash
make down
```

Stop containers and delete Docker volumes and local data for a clean reset:

```bash
make down-reset
```

## Recommended Reviewer Flow

```bash
make fresh-start
make smoke
make urls
```

Then:

1. Open the API docs and verify the service is reachable.
2. Open Grafana and review the provisioned dashboards.
3. Open Jaeger and confirm traces are being emitted.
4. Open Langfuse and confirm LLM telemetry is available.
5. Use `make logs` if any service looks unhealthy.
