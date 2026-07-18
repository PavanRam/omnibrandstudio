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
    """Load per-step checkpointed state so API can expose in-memory agent output."""
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

    timeline: list[dict[str, Any]] = []
    for snapshot in reversed(history):
        values = snapshot.values or {}
        task_names = [getattr(task, "name", str(task)) for task in (snapshot.tasks or [])]

        timeline.append(
            {
                "step": snapshot.metadata.get("step"),
                "source": snapshot.metadata.get("source"),
                "created_at": snapshot.created_at,
                "agents": task_names,
                "next": list(snapshot.next or ()),
                "state": {
                    "current_phase": values.get("current_phase"),
                    "variants": values.get("variants") or [],
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
