# Infrastructure Guide

This directory contains the local infrastructure configuration used by Docker
Compose and the observability stack.

## Main Areas

| Path | Purpose |
| --- | --- |
| `grafana/` | Provisioned dashboards, datasources, folders, and dashboard JSON |
| `prometheus/` | Prometheus scrape and rule configuration |
| `litellm/` | LiteLLM model alias and routing configuration |
| `nginx/` | Reverse-proxy related assets when needed |

## Runtime Role

The infrastructure layer supports:

- local service orchestration via Docker Compose
- model routing through LiteLLM aliases
- metrics collection through Prometheus
- dashboarding through Grafana
- tracing via Jaeger and Langfuse integration at runtime

## Use With

```bash
make up
make restart
make urls
make logs
```

## Working Notes

- Use `make up` or `make restart` instead of manually starting individual services unless you are debugging a specific container.
- Grafana dashboards and datasources are provisioned from source-controlled files in this repository.
- LiteLLM aliases are part of the application contract; application code should reference aliases, not raw provider model names.
