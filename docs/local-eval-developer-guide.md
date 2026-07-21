# Local Eval Developer Guide

This guide documents how to run local evaluation without Docker dependencies and how to run the unchanged production-like E2E path.

## Scope

- Local eval endpoint: `POST /eval/local-eval`
- Intended use: rapid agent validation and integration tests
- Route registration guardrails:
  - `ENABLE_LOCAL_EVAL=true`
  - `APP_ENV != production`

## Local Dev Mode (No Docker)

### 1) Install dependencies

```bash
uv sync --dev
```

### 2) Start API in local-dev mode

Bash:

```bash
make run-local-eval
```

PowerShell:

```powershell
$env:LOCAL_DEV_MODE="1"
$env:ENABLE_LOCAL_EVAL="1"
cd backend
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3) Verify service health

```bash
curl -s http://localhost:8000/health
```

PowerShell:

```powershell
Invoke-RestMethod -Method Get -Uri http://localhost:8000/health
```

### 4) Run local eval request

Bash:

```bash
curl -s -X POST http://localhost:8000/eval/local-eval \
  -H "Content-Type: application/json" \
  -d '{
    "brand_id": "00000000-0000-0000-0000-000000000002",
    "objective": "Validate new agent behavior",
    "target_audience": "Developers",
    "key_messages": ["Fast feedback", "No infra dependency"],
    "channels": ["email"],
    "locales": ["en-US"],
    "audience_segments": ["core"],
    "token_budget": 1000,
    "raw_text": ""
  }'
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/eval/local-eval -ContentType "application/json" -Body (@{
  brand_id = "00000000-0000-0000-0000-000000000002"
  objective = "Validate new agent behavior"
  target_audience = "Developers"
  key_messages = @("Fast feedback", "No infra dependency")
  channels = @("email")
  locales = @("en-US")
  audience_segments = @("core")
  token_budget = 1000
  raw_text = ""
} | ConvertTo-Json -Depth 8)
```

Expected response shape:

```json
{
  "campaign_id": "...",
  "status": "completed",
  "elapsed_ms": 123,
  "final_state": { "current_phase": "published", "errors": [] }
}
```

### 5) Run focused local-eval tests

```bash
make test-local-eval
```

## Production-like E2E (Unchanged)

Use this path to validate the default stack and ensure local eval changes do not affect production-like behavior.

### 1) Start infrastructure

```bash
make up
```

### 2) Start API

```bash
make run
```

### 3) Start worker

```bash
make worker
```

### 4) Run smoke tests

```bash
make smoke
```

## Cleanup Before Go-Live

Temporary local-only branches are marked with comment prefix `TEMP_LOCAL_EVAL`.

Find all tagged code paths:

```bash
rg "TEMP_LOCAL_EVAL"
```

PowerShell (if ripgrep is unavailable):

```powershell
Get-ChildItem -Recurse -File | Select-String -Pattern "TEMP_LOCAL_EVAL"
```
