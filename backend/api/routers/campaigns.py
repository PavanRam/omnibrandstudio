import json
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from opentelemetry.propagate import inject
from sqlalchemy import text

from core.config import settings
from core.database import get_db
from core.ids import new_campaign_id
from core.redis import get_redis
from pipeline.graph import build_graph
from pipeline.schemas import CreateCampaignRequest, ReviewDecision

router = APIRouter()
log = structlog.get_logger()

QUEUE = "campaigns:queue"
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
CAMPAIGN_NOT_FOUND = "campaign not found"


def _to_psycopg_dsn(raw_dsn: str) -> str:
    """Return a psycopg-compatible DSN and escape bare percent signs in auth."""
    dsn = raw_dsn.replace("+asyncpg", "")
    parts = urlsplit(dsn)
    if "@" not in parts.netloc:
        return dsn

    userinfo, hostpart = parts.netloc.rsplit("@", 1)
    if "%" not in userinfo:
        return dsn

    safe_userinfo = userinfo.replace("%", "%25")
    safe_netloc = f"{safe_userinfo}@{hostpart}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


async def _load_in_memory_trace(campaign_id: str) -> list[dict[str, Any]]:
    """Load per-step checkpointed state + agent input/output + cost attribution for observability."""
    psycopg_dsn = _to_psycopg_dsn(settings.POSTGRES_DSN)
    config = {"configurable": {"thread_id": campaign_id}}

    try:
        async with AsyncPostgresSaver.from_conn_string(psycopg_dsn) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer)
            history = [snapshot async for snapshot in graph.aget_state_history(config)]
    except Exception as exc:  # noqa: BLE001
        log.warning("campaign_in_memory_trace_unavailable", campaign_id=campaign_id, error=str(exc))
        return []

    # Load cost attribution data keyed by agent name (ordered by created_at)
    cost_data: dict[str, list[dict[str, Any]]] = {}
    try:
        db = await get_db()
        query = text("""
            SELECT agent_name, model_alias, input_tokens, output_tokens, total_cost_usd, latency_ms, langfuse_trace_id
            FROM campaign_cost_attribution
            WHERE campaign_id = :campaign_id::uuid
            ORDER BY created_at ASC
        """)
        result = await db.execute(query, {"campaign_id": campaign_id})
        for row in result.fetchall():
            agent = row[0]
            if agent not in cost_data:
                cost_data[agent] = []
            cost_data[agent].append({
                "model_alias": row[1],
                "input_tokens": row[2],
                "output_tokens": row[3],
                "cost_usd": float(row[4]) if row[4] is not None else None,
                "latency_ms": row[5],
                "langfuse_trace_id": row[6],
            })
    except Exception as exc:  # noqa: BLE001
        log.warning("campaign_cost_attribution_unavailable", campaign_id=campaign_id, error=str(exc))

    _FAN_IN_FIELDS = ("variants", "brand_scores", "aggregated_scores",
                      "review_requests", "publication_receipts", "failed_task_ids", "errors")
    _SCALAR_FIELDS = ("current_phase", "human_review_requested", "publishing_paused",
                      "token_cost_usd", "brief_valid", "current_task")

    def _summarise_variants(variants: list) -> list[dict]:
        out = []
        for v in variants or []:
            if not isinstance(v, dict):
                continue
            # Prefer the most-processed content available
            content = (v.get("personalized_content") or v.get("generated_content") or "")
            out.append({
                "task_id": v.get("task_id"),
                "channel": v.get("channel"),
                "locale": v.get("locale"),
                "segment": v.get("segment"),
                "status": v.get("status"),
                "content_preview": content[:200] if content else None,
                "failure_reason": v.get("failure_reason"),
            })
        return out

    def _diff_state(prev: dict, curr: dict) -> dict:
        """Return the fields that changed or were appended between two state snapshots."""
        delta: dict[str, Any] = {}
        # Fan-in list fields: only the newly added items
        for field in _FAN_IN_FIELDS:
            prev_items = prev.get(field) or []
            curr_items = curr.get(field) or []
            if len(curr_items) > len(prev_items):
                new_items = curr_items[len(prev_items):]
                delta[field] = _summarise_variants(new_items) if field == "variants" else new_items
        # Scalar fields: changed value
        for field in _SCALAR_FIELDS:
            prev_val = prev.get(field)
            curr_val = curr.get(field)
            if curr_val != prev_val and curr_val is not None:
                delta[field] = curr_val
        return delta

    def _agent_input_context(agent_name: str, prev_vals: dict) -> dict:
        """Build a focused input summary for each known agent type."""
        brief = prev_vals.get("brief") or {}
        if agent_name == "intake_agent":
            return {
                "brief_objective": brief.get("objective"),
                "channels": brief.get("channels"),
                "locales": brief.get("locales"),
                "audience_segments": brief.get("audience_segments"),
                "target_audience": brief.get("target_audience"),
                "key_messages": brief.get("key_messages"),
                "token_budget": brief.get("token_budget"),
            }
        if agent_name == "content_generator":
            return {
                "tasks": [
                    {"task_id": t.get("task_id"), "channel": t.get("channel"),
                     "locale": t.get("locale"), "segment": t.get("segment")}
                    for t in (prev_vals.get("tasks") or [])
                    if isinstance(t, dict)
                ],
                "brief_objective": brief.get("objective"),
                "key_messages": brief.get("key_messages"),
                "tone": brief.get("tone_override"),
                "rag_context_available": prev_vals.get("rag_context") is not None,
            }
        if agent_name == "personalization_agent":
            return {
                "variants_in": _summarise_variants(prev_vals.get("variants")),
                "audience_segments": brief.get("audience_segments"),
                "target_audience": brief.get("target_audience"),
            }
        if agent_name in ("judge_claude", "judge_gpt4o", "judge_llama"):
            return {
                "variants_to_judge": len(prev_vals.get("variants") or []),
                "variant_task_ids": [
                    v.get("task_id") for v in (prev_vals.get("variants") or [])
                    if isinstance(v, dict)
                ],
            }
        if agent_name == "confidence_aggregator":
            return {"brand_scores_in": prev_vals.get("brand_scores") or []}
        if agent_name == "review_gate":
            return {
                "aggregated_scores": prev_vals.get("aggregated_scores") or [],
                "human_review_requested": prev_vals.get("human_review_requested"),
            }
        if agent_name == "publication_agent":
            return {
                "review_requests": prev_vals.get("review_requests") or [],
                "variants_count": len(prev_vals.get("variants") or []),
            }
        return {}

    # history is newest-first; reverse to get chronological order
    snapshots = list(reversed(history))

    timeline: list[dict[str, Any]] = []
    for idx, snapshot in enumerate(snapshots):
        values = snapshot.values or {}
        meta = snapshot.metadata or {}

        # Agents that RAN to produce this snapshot = what was scheduled in the PREVIOUS step
        if idx == 0:
            agents_ran: list[str] = []
            agent_output: dict[str, Any] = {}
            agent_input: dict[str, Any] = {}
        else:
            prev_snapshot = snapshots[idx - 1]
            agents_ran = list(prev_snapshot.next or ())
            prev_vals = prev_snapshot.values or {}

            # What changed between prev and curr = agent output (delta)
            delta = _diff_state(prev_vals, values)

            # Assign the delta to every agent that ran this step
            agent_output = {agent: delta for agent in agents_ran} if (agents_ran and delta) else {}

            # Build focused input context per agent
            agent_input = {
                agent: _agent_input_context(agent, prev_vals)
                for agent in agents_ran
            }

        # Cost attribution for agents that ran this step
        agent_metadata: dict[str, Any] = {}
        for agent_name in agents_ran:
            if agent_name in cost_data and cost_data[agent_name]:
                agent_metadata[agent_name] = cost_data[agent_name].pop(0)

        timeline.append(
            {
                "step": meta.get("step"),
                "source": meta.get("source"),
                "created_at": snapshot.created_at,
                "agents": agents_ran,
                "next": list(snapshot.next or ()),
                "agent_input": agent_input,
                "agent_output": agent_output,
                "agent_metadata": agent_metadata,
                "state": {
                    "current_phase": values.get("current_phase"),
                    "variant_count": len(values.get("variants") or []),
                    "variants": _summarise_variants(values.get("variants")),
                    "brand_scores": values.get("brand_scores") or [],
                    "aggregated_scores": values.get("aggregated_scores") or [],
                    "review_requests": values.get("review_requests") or [],
                    "publication_receipts": values.get("publication_receipts") or [],
                    "failed_task_ids": values.get("failed_task_ids") or [],
                    "errors": values.get("errors") or [],
                    "human_review_requested": values.get("human_review_requested"),
                    "publishing_paused": values.get("publishing_paused"),
                    "token_cost_usd": values.get("token_cost_usd"),
                },
            }
        )

    return timeline


def _normalize_org_id(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except ValueError:
            return DEFAULT_ORG_ID
    return DEFAULT_ORG_ID


def _normalize_brand_id(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="brand_id must be a valid UUID",
            ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="brand_id must be a valid UUID",
    )


def _normalize_campaign_id(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="campaign_id must be a valid UUID",
            ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="campaign_id must be a valid UUID",
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_campaign(
    body: CreateCampaignRequest,
    request: Request,
) -> dict:
    """Create and immediately enqueue a campaign for processing.

    Returns 202 Accepted with the campaign_id.  Clients should poll
    GET /campaigns/{id}/status for progress.
    """
    campaign_id = new_campaign_id()
    request_id = getattr(request.state, "request_id", "")
    org_id = _normalize_org_id(getattr(request.state, "org_id", None))
    brand_id = _normalize_brand_id(body.brand_id)
    user_id = getattr(request.state, "user_id", "")

    brief_payload = body.model_dump()

    async with get_db() as conn:
        brand_result = await conn.execute(
            text(
                """
                SELECT id, org_id
                FROM brands
                WHERE id = :brand_id
                """
            ),
            {"brand_id": brand_id},
        )
        brand_row = brand_result.mappings().first()
        if brand_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")
        if str(brand_row["org_id"]) != org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="brand does not belong to org")

        await conn.execute(
            text(
                """
                INSERT INTO campaigns (id, org_id, brand_id, created_by, brief, status)
                VALUES (:id, :org_id, :brand_id, :created_by, CAST(:brief AS JSONB), :status)
                """
            ),
            {
                "id": campaign_id,
                "org_id": org_id,
                "brand_id": brand_id,
                "created_by": user_id or None,
                "brief": json.dumps(brief_payload),
                "status": "queued",
            },
        )
        await conn.commit()

    task = {
        "campaign_id": campaign_id,
        "org_id": org_id,
        "brand_id": brand_id,
        "user_id": user_id,
        "request_id": request_id,
        "brief": brief_payload,
    }
    trace_carrier: dict[str, str] = {}
    inject(trace_carrier)
    task["_trace_context"] = trace_carrier
    redis = get_redis()
    await redis.lpush(QUEUE, json.dumps(task))

    log.info(
        "campaign_enqueued",
        campaign_id=campaign_id,
        brand_id=brand_id,
        request_id=request_id,
    )
    return {
        "campaign_id": campaign_id,
        "status": "queued",
        "poll_url": f"/campaigns/{campaign_id}/status",
    }


@router.post("/{campaign_id}/run")
async def run_campaign(campaign_id: str) -> dict:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "campaigns run not yet implemented")


@router.post("/{campaign_id}/approval")
async def approve_campaign(campaign_id: str, body: ReviewDecision) -> dict:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, status
                FROM campaigns
                WHERE id = :campaign_id
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        campaign_row = result.mappings().first()

        if campaign_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)

        current_status = str(campaign_row["status"])
        if current_status not in {"awaiting_review", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"campaign status '{current_status}' is not reviewable",
            )

        status_by_decision = {
            "approved": "published",
            "rejected": "cancelled",
            "edited": "published",
        }
        next_status = status_by_decision[body.decision]

        await conn.execute(
            text(
                """
                UPDATE campaigns
                SET status = :status,
                    completed_at = NOW()
                WHERE id = :campaign_id
                """
            ),
            {
                "campaign_id": normalized_campaign_id,
                "status": next_status,
            },
        )
        await conn.commit()

    return {
        "campaign_id": normalized_campaign_id,
        "decision": body.decision,
        "status": next_status,
        "reviewer_note": body.reviewer_note,
    }


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)
    in_memory_trace = await _load_in_memory_trace(normalized_campaign_id)

    async with get_db() as conn:
        campaign_result = await conn.execute(
            text(
                """
                SELECT id, org_id, brand_id, status, token_cost_usd, created_at, started_at, completed_at, brief
                FROM campaigns
                WHERE id = :campaign_id
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        campaign_row = campaign_result.mappings().first()

        if campaign_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)

        variants_result = await conn.execute(
            text(
                """
                SELECT
                    v.task_id,
                    v.locale,
                    v.channel,
                    v.segment,
                    v.status,
                    v.final_content,
                    a.weighted_mean AS composite_score
                FROM content_variants v
                LEFT JOIN aggregated_scores a ON a.variant_id = v.id
                WHERE v.campaign_id = :campaign_id
                ORDER BY v.created_at ASC
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        variant_rows = variants_result.mappings().all()

    return {
        "id": str(campaign_row["id"]),
        "org_id": str(campaign_row["org_id"]),
        "brand_id": str(campaign_row["brand_id"]),
        "status": str(campaign_row["status"]),
        "token_cost_usd": float(campaign_row["token_cost_usd"]),
        "created_at": campaign_row["created_at"],
        "started_at": campaign_row["started_at"],
        "completed_at": campaign_row["completed_at"],
        "brief": campaign_row["brief"] or {},
        "in_memory_trace": in_memory_trace,
        "variants": [
            {
                "task_id": str(row["task_id"]),
                "locale": str(row["locale"]),
                "channel": str(row["channel"]),
                "segment": str(row["segment"]),
                "status": str(row["status"]),
                "final_content": row["final_content"],
                "composite_score": (
                    float(row["composite_score"]) if row["composite_score"] is not None else None
                ),
            }
            for row in variant_rows
        ],
    }


@router.get("/{campaign_id}/status")
async def get_campaign_status(campaign_id: str) -> dict:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, status, started_at, completed_at, token_cost_usd, created_at
                FROM campaigns
                WHERE id = :campaign_id
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)

    return {
        "campaign_id": str(row["id"]),
        "status": str(row["status"]),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "token_cost_usd": float(row["token_cost_usd"]),
        "created_at": row["created_at"],
    }
