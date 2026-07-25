# Review Gate and Human Review: Run and Test Guide

A step-by-step guide to exercise the human-in-the-loop review flow end to end with the full Docker stack and Postman. The steps mirror a verified run.

## Overview

The review gate only triggers on the worker path (`POST /campaigns`). The worker runs the pipeline, the graph pauses before `review_gate` using `interrupt_before`, the review batch is persisted, and the campaign moves to `awaiting_review`. A reviewer then lists pending reviews and submits a decision, which resumes the graph.

> [!WARNING]
> Do not use `/eval/local-eval` for review testing. That endpoint runs the graph inline with the interrupt disabled and never persists a campaign row. It will not pause for review, and `GET /campaigns/{id}/status` will return `404`.

## Prerequisites

- Docker Desktop is running.
- A valid `GROQ_API_KEY` is present in the repository-root `.env`. Content must generate successfully or no variant will be reviewable and the campaign will not pause.
- The review-gate code and its supporting fixes are available.
- `LOCAL_DEV_MODE` is not set; Docker uses the real services.

## Review Lifecycle

```text
POST /campaigns
  → API adds campaign to Redis queue
  → worker runs intake, generation, judges, and aggregation
  → graph interrupts before review_gate
  → review_requests are persisted
  → campaign status becomes awaiting_review
  → reviewer calls GET /reviews
  → reviewer calls POST /reviews/{id}/decide
  → graph state is updated and execution resumes
      ├─ approved or edited → published
      └─ rejected → regenerate → pause again
```

## 1. Bring Up the Stack and Create the Schema

### 1.1 Start all services

```bash
docker compose up -d --build
```

Wait until `docker compose ps` shows `postgres`, `redis`, and `litellm` as healthy and `api` and `worker` as running.

### 1.2 Apply migrations

```bash
docker compose exec api python -m alembic upgrade head
```

## 2. Seed an Organization, Brand, and API Key

The `/reviews` endpoints require authentication, and `POST /campaigns` needs a brand under the default organization (`…0001`). Run the following once from PowerShell at the repository root:

```powershell
@'
INSERT INTO orgs (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001','Demo Org','demo-org')
ON CONFLICT (id) DO NOTHING;

INSERT INTO brands (id, org_id, name)
VALUES (
  '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  'Demo Brand'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO api_keys (org_id, brand_id, name, key_hash, key_prefix, scopes)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000002',
  'demo-key',
  encode(digest('omnibrand-demo-key','sha256'),'hex'),
  'omnibrand',
  ARRAY['campaigns:read','campaigns:write','reviews:read','reviews:decide']
)
ON CONFLICT (key_hash) DO NOTHING;
'@ | docker compose exec -T postgres psql -U omnibrand -d omnibrand
```

The reviewer API key is `omnibrand-demo-key`. Its SHA-256 value is stored; the application hashes the incoming `X-API-Key` and matches it.

## 3. Configure Postman

Add these collection variables:

| Variable | Value |
|---|---|
| `base_url` | `http://localhost:8000` |
| `api_key` | `omnibrand-demo-key` |
| `campaign_id` | Filled from Request 1 |
| `review_request_id` | Filled from Request 3 |

## 4. Test the Review Flow

### Request 1: Create a Campaign

`POST {{base_url}}/campaigns`

- Authentication: none; the server uses the default organization.
- Header: `Content-Type: application/json`
- Body:

```json
{
  "brand_id": "00000000-0000-0000-0000-000000000002",
  "objective": "Launch our new API",
  "target_audience": "Developers",
  "key_messages": ["Fast", "Reliable"],
  "channels": ["email"],
  "locales": ["en-US"],
  "audience_segments": ["core"],
  "token_budget": 2000,
  "raw_text": ""
}
```

Expected `202` response:

```json
{
  "campaign_id": "019f…",
  "status": "queued",
  "poll_url": "/campaigns/019f…/status"
}
```

Use one channel, locale, and segment to create exactly one review. Save `campaign_id` in Postman.

### Request 2: Poll Until the Campaign Pauses

`GET {{base_url}}/campaigns/{{campaign_id}}/status`

Authentication is not required. Send the request every few seconds until `status` becomes `awaiting_review`, typically after 10–45 seconds:

```json
{
  "campaign_id": "019f…",
  "status": "awaiting_review",
  "started_at": "…",
  "created_at": "…"
}
```

To watch the worker, run:

```bash
docker compose logs -f worker
```

Look for `review_batch_persisted`.

### Request 3: List Pending Reviews

`GET {{base_url}}/reviews?status=pending&limit=20&offset=0`

Set the required header `X-API-Key: {{api_key}}`.

Expected `200` response:

```json
{
  "reviews": [
    {
      "review_request_id": "11cf88d6-…",
      "variant_id": "…",
      "campaign_id": "019f…",
      "task_id": "en-US_email_core",
      "locale": "en-US",
      "channel": "email",
      "segment": "core",
      "status": "pending",
      "routing_reason": "flagged for human review",
      "sla_deadline": "…",
      "content": "Subject: …",
      "composite_score": 6.5,
      "scores_snapshot": [
        {"judge_model": "claude"},
        {"judge_model": "gpt4o"},
        {"judge_model": "llama"}
      ]
    }
  ],
  "limit": 20,
  "offset": 0,
  "count": 1
}
```

Save `review_request_id` in Postman.

### Request 4: Submit a Decision

`POST {{base_url}}/reviews/{{review_request_id}}/decide`

Set these headers:

```text
X-API-Key: {{api_key}}
Content-Type: application/json
```

The body is mandatory. An empty body returns `422 "Field required"`.

| Decision | Body | Result |
|---|---|---|
| Approve | `{"decision":"approved","reviewer_note":"ship it"}` | Publishes as-is |
| Edit | `{"decision":"edited","edited_content":"Subject: Final copy\n\n…","reviewer_note":"tightened CTA"}` | Publishes `edited_content` as `final_content` |
| Reject | `{"decision":"rejected","reviewer_note":"too generic, redo"}` | Regenerates and pauses again |

> [!IMPORTANT]
> `edited_content` is required for `edited` and must be omitted for `approved` and `rejected`; otherwise the API returns `422`.

Expected `200` response when this is the campaign's last pending review:

```json
{
  "review_request_id": "…",
  "decision": "approved",
  "status": "resumed",
  "campaign_status": "published"
}
```

Expected `202` response when other campaign reviews remain pending:

```json
{
  "review_request_id": "…",
  "decision": "approved",
  "status": "recorded",
  "campaign_status": "awaiting_review",
  "detail": "awaiting remaining reviews for this campaign"
}
```

### Request 5: Verify the Outcome

`GET {{base_url}}/campaigns/{{campaign_id}}`

Authentication is not required. For an approval or edit, expect:

```json
{
  "id": "019f…",
  "status": "published",
  "variants": [
    {
      "task_id": "en-US_email_core",
      "status": "approved",
      "final_content": "Subject: …",
      "composite_score": 6.5
    }
  ],
  "in_memory_trace": ["…"]
}
```

For an edit, `final_content` is the submitted text and the variant `status` is `edited`.

## Database and Audit Checks

These checks are optional:

```powershell
docker compose exec -T postgres psql -U omnibrand -d omnibrand -c ^
  "SELECT status, decision, reviewed_at FROM review_requests WHERE campaign_id='<campaign_id>';"

docker compose exec -T postgres psql -U omnibrand -d omnibrand -c ^
  "SELECT action, entity_type FROM audit_log WHERE entity_type='review_request' ORDER BY created_at DESC LIMIT 3;"
```

Expect the `review_requests` row to be `approved` with `reviewed_at` set, and an `audit_log` row with `action = decide`.

## Airtable Setup and Mirror

The Airtable mirror is optional, configuration-gated, and best-effort. PostgreSQL `review_requests` remains the source of truth; Airtable mirrors pending and decided reviews for reviewer visibility. If Airtable is not configured, the integration is a no-op and does not affect the pipeline.

### 1. Create a Base

Create an Airtable base such as `OmniBrand Reviews` and rename its default table to `Reviews`.

### 2. Add Fields

Field names are case-sensitive and must match exactly:

| Field | Type |
|---|---|
| `review_request_id` | Single line text |
| `campaign_id` | Single line text |
| `variant_id` | Single line text |
| `status` | Single line text, or single select with `pending`, `approved`, `rejected`, and `edited` |
| `routing_reason` | Long text |
| `decision` | Single line text, or single select with `approved`, `rejected`, and `edited` |

The default primary field can remain; the mirror does not write it.

### 3. Get the Base ID

Open [Airtable's Web API documentation](https://airtable.com/developers/web/api/introduction) and select the base. The Base ID starts with `app` and also appears in the base URL.

### 4. Create a Personal Access Token

Create a token at [Airtable token management](https://airtable.com/create/tokens) with `data.records:read` and `data.records:write` scopes and access to the base.

### 5. Configure the Environment

Add these values to the repository-root `.env`:

```dotenv
AIRTABLE_API_KEY=patXXXXXXXXXXXXXX.XXXXXXXXXXXXXXXX
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
AIRTABLE_TABLE=Reviews
```

All three values must be non-empty for `airtable_enabled()` to activate the mirror. Do not commit `.env`; the token is a secret.

### 6. Reload and Verify

```bash
docker compose up -d api worker
```

Run a campaign through Requests 1–4. A row is upserted when the graph pauses, and a decision row is appended when the decision is submitted.

> [!NOTE]
> Airtable failures are non-fatal. Invalid credentials, IDs, table names, or fields produce an `airtable_mirror_failed` warning in `docker compose logs api worker`; the pipeline continues and PostgreSQL remains the source of truth.

Quick sanity check:

```bash
uv run python - <<'PY'
import os

import httpx

env = dict(
    line.strip().split("=", 1)
    for line in open(".env")
    if "=" in line and not line.startswith("#")
)
key = env.get("AIRTABLE_API_KEY", "")
base = env.get("AIRTABLE_BASE_ID", "")
table = env.get("AIRTABLE_TABLE", "Reviews")
print("configured:", bool(key), bool(base), table)

if key and base:
    response = httpx.get(
        f"https://api.airtable.com/v0/{base}/{table}",
        headers={"Authorization": f"Bearer {key}"},
        params={"maxRecords": 5},
        timeout=15,
    )
    count = len(response.json().get("records", [])) if response.status_code == 200 else response.text[:200]
    print("HTTP", response.status_code, "records:", count)
PY
```

## Troubleshooting

| Symptom | Cause or fix |
|---|---|
| `401` on `/reviews` | The `X-API-Key` is missing or incorrect, or the seed step did not run. |
| `422 "Field required"` on decide | The body is empty. Select raw JSON and provide a decision. |
| `422` concerning `edited_content` | `edited_content` was sent with approve/reject or omitted with edit. |
| Campaign never reaches `awaiting_review` | Content generation failed. Check worker logs for `llm_call_http_failed_using_fallback`. |
| `404` brand not found on `/campaigns` | The seed did not run or the brand is not under organization `…0001`. |
| `409` on decide | The review request was already decided. Get a fresh pending review from Request 3. |
| Connection refused | Docker Desktop or the stack is not running. |

## Verified and Partial Paths

| Path | Status | Notes |
|---|---|---|
| Approve | Verified end to end | Docker and Postman produce `published`; database and audit records were confirmed. |
| Edit | Verified path | Uses the same apply, resume, and publish flow and publishes the edited text. |
| Reject | Partial | Regenerates and pauses again, capped by `MAX_REVIEW_ROUNDS=2`. The API-driven second round is not yet actionable because the regenerated review is not persisted on the second pause, so `GET /reviews` does not list it. |

## Endpoint Reference

- `POST /campaigns`
- `GET /campaigns/{id}/status`
- `GET /campaigns/{id}`
- `GET /reviews`
- `POST /reviews/{id}/decide`

Design reference: `docs/superpowers/specs/2026-07-19-t11-review-gate-design.md`.
