import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from opentelemetry.propagate import inject
from pydantic import BaseModel
from sqlalchemy import text

from api.deps import UserContext, get_current_user
from core.config import settings
from core.database import get_db
from core.ids import new_campaign_id
from core.redis import get_redis
from pipeline.graph import build_graph
from pipeline.schemas import CreateCampaignRequest, ReviewDecision
from services import review_service
from services.campaign import archive_service
from services.campaign.rerun_service import rerun_service

router = APIRouter()
log = structlog.get_logger()

QUEUE = "campaigns:queue"
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
CAMPAIGN_NOT_FOUND = "campaign not found"


class RerunCampaignRequest(BaseModel):
    resume_from_node: str
    trigger: Literal["initial", "edit_content", "add_channel", "regenerate"] = "regenerate"
    user_edit: str | None = None
    variant_task_id: str | None = None


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


_FAN_IN_FIELDS = (
    "variants",
    "brand_scores",
    "aggregated_scores",
    "review_requests",
    "publication_receipts",
    "failed_task_ids",
    "errors",
)
_SCALAR_FIELDS = (
    "current_phase",
    "human_review_requested",
    "publishing_paused",
    "token_cost_usd",
    "brief_valid",
    "current_task",
)


async def _load_cost_attribution(campaign_id: str) -> dict[str, list[dict[str, Any]]]:
    cost_data: dict[str, list[dict[str, Any]]] = {}
    try:
        async with get_db() as conn:
            # 2026-07-27: this previously selected a `langfuse_trace_id` column
            # that was never actually created in any migration (001_core_schema
            # only has agent_name/model_alias/model_resolved/provider/
            # input_tokens/output_tokens/cached_tokens/total_cost_usd/
            # was_cached/latency_ms/created_at) — confirmed live via a real
            # UndefinedColumnError, meaning this function has been silently
            # failing (caught below, returning {}) on every real invocation.
            # Dropped the nonexistent column rather than adding a migration
            # for a field nothing else needs yet.
            query = text(
                """
                SELECT agent_name, model_alias, input_tokens, output_tokens, total_cost_usd, latency_ms
                FROM campaign_cost_attribution
                WHERE campaign_id = CAST(:campaign_id AS UUID)
                ORDER BY created_at ASC
                """
            )
            result = await conn.execute(query, {"campaign_id": campaign_id})
            for row in result.fetchall():
                agent = row[0]
                if agent not in cost_data:
                    cost_data[agent] = []
                cost_data[agent].append(
                    {
                        "model_alias": row[1],
                        "input_tokens": row[2],
                        "output_tokens": row[3],
                        "cost_usd": float(row[4]) if row[4] is not None else None,
                        "latency_ms": row[5],
                    }
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("campaign_cost_attribution_unavailable", campaign_id=campaign_id, error=str(exc))
    return cost_data


def _summarise_variants(variants: list) -> list[dict]:
    def _preview(value: Any, limit: int = 280) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        return text[:limit]

    out = []
    for v in variants or []:
        if not isinstance(v, dict):
            continue
        out.append(
            {
                "task_id": v.get("task_id"),
                "channel": v.get("channel"),
                "locale": v.get("locale"),
                "segment": v.get("segment"),
                "status": v.get("status"),
                "generated_preview": _preview(v.get("generated_content")),
                "personalized_preview": _preview(v.get("personalized_content")),
                "translated_preview": _preview(v.get("translated_content")),
                "final_preview": _preview(v.get("final_content")),
                "failure_reason": v.get("failure_reason"),
            }
        )
    return out


def _diff_state(prev: dict, curr: dict) -> dict:
    delta: dict[str, Any] = {}
    for field in _FAN_IN_FIELDS:
        prev_items = prev.get(field) or []
        curr_items = curr.get(field) or []
        if len(curr_items) > len(prev_items):
            new_items = curr_items[len(prev_items):]
            delta[field] = _summarise_variants(new_items) if field == "variants" else new_items
    for field in _SCALAR_FIELDS:
        prev_val = prev.get(field)
        curr_val = curr.get(field)
        if curr_val != prev_val and curr_val is not None:
            delta[field] = curr_val
    return delta


def _agent_input_context(agent_name: str, prev_vals: dict) -> dict:
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
                {
                    "task_id": t.get("task_id"),
                    "channel": t.get("channel"),
                    "locale": t.get("locale"),
                    "segment": t.get("segment"),
                }
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
                v.get("task_id") for v in (prev_vals.get("variants") or []) if isinstance(v, dict)
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


def _build_timeline_state(values: dict) -> dict:
    return {
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
    }


def _build_agent_metadata(agents_ran: list[str], cost_data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for agent_name in agents_ran:
        if agent_name in cost_data and cost_data[agent_name]:
            metadata[agent_name] = cost_data[agent_name].pop(0)
    return metadata


def _build_step_agent_views(idx: int, snapshots: list, values: dict) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    if idx == 0:
        return [], {}, {}
    prev_snapshot = snapshots[idx - 1]
    agents_ran = list(prev_snapshot.next or ())
    prev_vals = prev_snapshot.values or {}
    delta = _diff_state(prev_vals, values)
    agent_output = dict.fromkeys(agents_ran, delta) if (agents_ran and delta) else {}
    agent_input = {agent: _agent_input_context(agent, prev_vals) for agent in agents_ran}
    return agents_ran, agent_input, agent_output


def _build_event_id(*, campaign_id: str, step: int, agent: str, event_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{campaign_id}:{step}:{agent}:{event_index}"))


def _build_event_summary(*, agent: str, phase: str, payload: dict[str, Any]) -> str:
    if "errors" in payload and payload.get("errors"):
        return f"{agent} reported errors during {phase}."
    variant_count = payload.get("variant_count")
    if isinstance(variant_count, int):
        return f"{agent} updated {phase}; variants now {variant_count}."
    return f"{agent} updated {phase}."


def _trace_to_replay_events(campaign_id: str, timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for step_idx, step in enumerate(timeline):
        events.extend(_trace_step_to_events(campaign_id=campaign_id, step=step, step_idx=step_idx))

    deduped: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        deduped.append(event)

    return deduped


def _window_replay_events(
    events: list[dict[str, Any]],
    *,
    limit: int,
    before_event_id: str | None,
) -> tuple[list[dict[str, Any]], bool, bool]:
    if not events:
        return [], False, before_event_id is None

    window = events
    has_more = False
    cursor_found = True

    if before_event_id:
        index = next((idx for idx, event in enumerate(events) if event.get("event_id") == before_event_id), -1)
        if index > 0:
            window = events[:index]
        elif index == 0:
            window = []
        else:
            return [], False, False

    if len(window) > limit:
        has_more = True
        window = window[-limit:]

    return window, has_more, cursor_found


def _trace_step_to_events(*, campaign_id: str, step: dict[str, Any], step_idx: int) -> list[dict[str, Any]]:
    step_number = int(step.get("step") or step_idx)
    state = step.get("state") or {}
    phase = str(state.get("current_phase") or "update")
    created_at = step.get("created_at")
    agent_output = step.get("agent_output") or {}
    agents = list(step.get("agents") or [])

    out: list[dict[str, Any]] = []
    for agent_idx, agent in enumerate(agents):
        event_payload = _build_replay_event_payload(state=state, agent_output=agent_output, agent=agent)
        event_id = _build_event_id(
            campaign_id=campaign_id,
            step=step_number,
            agent=agent,
            event_index=agent_idx,
        )
        out.append(
            {
                "event_id": event_id,
                "campaign_id": campaign_id,
                "timestamp": created_at,
                "agent": agent,
                "phase": phase,
                "summary": _build_event_summary(agent=agent, phase=phase, payload=event_payload),
                "payload": event_payload,
                "source": "replay",
            }
        )
    return out


def _build_replay_event_payload(
    *,
    state: dict[str, Any],
    agent_output: dict[str, Any],
    agent: str,
) -> dict[str, Any]:
    payload = agent_output.get(agent)
    normalized_payload = payload if isinstance(payload, dict) else {}
    variants = state.get("variants")
    variant_list = variants if isinstance(variants, list) else []
    variant_samples = variant_list[:3]
    enriched: dict[str, Any] = {
        **normalized_payload,
        "variant_count": state.get("variant_count", 0),
        "human_review_requested": state.get("human_review_requested", False),
        "variant_samples": variant_samples,
    }
    # The live pub/sub events carry per-agent progress counts the checkpoint
    # delta doesn't (personalized/translated + per-locale tasks), so replay of
    # a completed campaign previously rendered "0 variants personalized/
    # translated" even when content existed. Recompute from checkpoint variants
    # so replay matches the live run panel.
    if agent == "personalization_agent":
        enriched["personalized"] = sum(
            1 for v in variant_list if isinstance(v, dict) and v.get("personalized_preview")
        )
    elif agent == "translation_agent":
        enriched["translated"] = sum(
            1
            for v in variant_list
            if isinstance(v, dict) and (v.get("translated_preview") or v.get("status") == "translated")
        )
        enriched["tasks"] = [
            {"task_id": v.get("task_id"), "status": v.get("status"), "locale": v.get("locale")}
            for v in variant_list
            if isinstance(v, dict)
        ]
    return enriched


def _normalize_live_stream_payload(normalized_campaign_id: str, payload: str) -> str:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        return payload

    parsed.setdefault("source", "live")
    if not parsed.get("event_id"):
        seed = (
            f"{normalized_campaign_id}:"
            f"{parsed.get('timestamp', '')}:"
            f"{parsed.get('agent', 'event')}:"
            f"{parsed.get('phase', 'update')}:"
            f"{json.dumps(parsed.get('payload', {}), sort_keys=True)}"
        )
        parsed["event_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
    return json.dumps(parsed)


def _message_payload_to_text(message: dict[str, Any]) -> str:
    data = message.get("data")
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


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

    cost_data = await _load_cost_attribution(campaign_id)

    # history is newest-first; reverse to get chronological order
    snapshots = list(reversed(history))

    timeline: list[dict[str, Any]] = []
    for idx, snapshot in enumerate(snapshots):
        values = snapshot.values or {}
        meta = snapshot.metadata or {}
        agents_ran, agent_input, agent_output = _build_step_agent_views(idx, snapshots, values)
        agent_metadata = _build_agent_metadata(agents_ran, cost_data)

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
                "state": _build_timeline_state(values),
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
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Create and immediately enqueue a campaign for processing.

    Returns 202 Accepted with the campaign_id.  Clients should poll
    GET /campaigns/{id}/status for progress.
    """
    campaign_id = new_campaign_id()
    request_id = getattr(request.state, "request_id", "")
    # org_id/user_id must come from the authenticated caller, not an
    # unpopulated request.state (nothing in this app's middleware sets those
    # attributes — reading them silently fell back to '' / DEFAULT_ORG_ID,
    # which meant every campaign was recorded with created_by=NULL regardless
    # of who actually created it).
    org_id = _normalize_org_id(user.org_id)
    brand_id = _normalize_brand_id(body.brand_id)
    user_id = user.user_id

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


@router.post("/{campaign_id}/send-to-review")
async def send_campaign_to_review(
    campaign_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Move a campaign from 'draft' to 'awaiting_review'.

    Called by the campaign's creator once they've previewed the generated
    content — not automatically by the pipeline. Also allowed for admin/editor,
    e.g. if the creator is unavailable and someone else needs to move it along.
    """
    normalized_campaign_id = _normalize_campaign_id(campaign_id)

    async with get_db() as conn:
        campaign_row = (
            await conn.execute(
                text("SELECT status, created_by FROM campaigns WHERE id = :campaign_id"),
                {"campaign_id": normalized_campaign_id},
            )
        ).mappings().first()

    if campaign_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CAMPAIGN_NOT_FOUND)

    is_creator = campaign_row["created_by"] is not None and str(campaign_row["created_by"]) == user.user_id
    is_manager = bool({"admin", "editor"} & set(user.roles))
    if not (is_creator or is_manager):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the campaign's creator or an admin/editor can send it to review")

    current_status = str(campaign_row["status"])
    if current_status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"campaign status '{current_status}' is not awaiting a send-to-review action",
        )

    try:
        review_count = await review_service.send_campaign_to_review(normalized_campaign_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return {
        "campaign_id": normalized_campaign_id,
        "status": "awaiting_review",
        "review_requests_created": review_count,
    }


@router.post("/{campaign_id}/archive")
async def archive_campaign_route(
    campaign_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Soft-archives a campaign (status='archived'), never a delete.

    Permission split (2026-07-26): admins can archive any campaign
    regardless of status. Regular users can only archive campaigns that
    are genuinely stuck or failed — never one that's `awaiting_review` or
    `published`. See services/campaign/archive_service.py for the exact
    "stuck" thresholds.
    """
    normalized_campaign_id = _normalize_campaign_id(campaign_id)
    is_admin = "admin" in user.roles

    try:
        await archive_service.archive_campaign(normalized_campaign_id, is_admin=is_admin)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    return {"campaign_id": normalized_campaign_id, "status": "archived"}


def _summarise_judge_reasoning(scores: dict[str, Any] | None) -> str:
    """One line for the Run summary panel's Judge gate row — the
    lowest-scoring criterion's own reasoning text is the most useful single
    line for understanding why a judge scored a variant the way it did,
    rather than concatenating every criterion (too long for a chip row)."""
    if not scores:
        return ""
    worst_key, worst = min(
        scores.items(), key=lambda kv: kv[1].get("score", 10) if isinstance(kv[1], dict) else 10
    )
    if not isinstance(worst, dict):
        return ""
    reasoning = str(worst.get("reasoning") or "").strip()
    return reasoning[:160]
def _optional_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


@router.get("/stats")
async def get_campaign_stats(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, int]:
    """Get campaign count statistics by status.

    Returns the totals for active campaign statuses (draft, pending, published, failed, total).
    """
    is_admin = "admin" in user.roles
    # Scoped identically to get_recent_campaigns:
    created_by = None if is_admin else _optional_uuid(user.user_id)
    brand_ids = user.brand_ids

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT status, COUNT(*) AS count
                FROM campaigns
                WHERE org_id = CAST(:org_id AS UUID)
                  AND (:brand_filter_disabled OR brand_id = ANY(CAST(:brand_ids AS UUID[])))
                  AND (CAST(:created_by AS UUID) IS NULL OR created_by = CAST(:created_by AS UUID))
                  AND status != 'archived'
                GROUP BY status
                """
            ),
            {
                "org_id": user.org_id,
                "brand_filter_disabled": len(brand_ids) == 0,
                "brand_ids": brand_ids,
                "created_by": created_by,
            },
        )
        rows = result.mappings().all()

    # Default/initial count values
    counts = {
        "total": 0,
        "draft": 0,
        "pending": 0,
        "published": 0,
        "failed": 0,
    }

    # Map database statuses to stats buckets
    # allowed statuses in DB: 'draft', 'queued', 'running', 'awaiting_review', 'published', 'failed', 'cancelled'
    for row in rows:
        status_val = str(row["status"])
        count_val = int(row["count"] or 0)
        
        # Increment total for any non-archived status
        counts["total"] += count_val
        
        if status_val == "draft":
            counts["draft"] += count_val
        elif status_val == "awaiting_review":
            counts["pending"] += count_val
        elif status_val == "published":
            counts["published"] += count_val
        elif status_val == "failed":
            counts["failed"] += count_val

    return counts


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)
    in_memory_trace = await _load_in_memory_trace(normalized_campaign_id)

    async with get_db() as conn:
        campaign_result = await conn.execute(
            text(
                """
                SELECT c.id, c.org_id, c.brand_id, c.status, c.token_cost_usd, c.created_at,
                       c.started_at, c.completed_at, c.brief, c.created_by, u.email AS creator_email
                FROM campaigns c
                LEFT JOIN users u ON u.id = c.created_by
                WHERE c.id = :campaign_id
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        campaign_row = campaign_result.mappings().first()

        if campaign_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)

        # Used by the read-only similar-campaign popup: if the current user
        # created this campaign, it links back to the conversation that
        # produced it instead of just showing an email address.
        conversation_result = await conn.execute(
            text(
                """
                SELECT id
                FROM conversations
                WHERE CAST(:campaign_id AS UUID) = ANY(campaign_ids)
                   OR active_campaign_id = CAST(:campaign_id AS UUID)
                LIMIT 1
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        conversation_row = conversation_result.mappings().first()

        variants_result = await conn.execute(
            text(
                """
                WITH latest_variants AS (
                    -- Edits (whole-campaign or single-channel) INSERT a fresh
                    -- content_variants row per re-run rather than updating in
                    -- place, so pick only the newest row per task_id here.
                    SELECT DISTINCT ON (task_id) *
                    FROM content_variants
                    WHERE campaign_id = :campaign_id
                    ORDER BY task_id, created_at DESC
                )
                SELECT
                    v.id,
                    v.task_id,
                    v.locale,
                    v.channel,
                    v.segment,
                    v.status,
                    v.final_content,
                    v.translation_engine,
                    v.back_translation_score,
                    v.failure_reason,
                    v.translation_checks,
                    a.weighted_mean AS composite_score
                FROM latest_variants v
                LEFT JOIN aggregated_scores a ON a.variant_id = v.id
                ORDER BY v.channel ASC, v.locale ASC
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        variant_rows = variants_result.mappings().all()

        # Per-judge score/reasoning for the "Run summary" panel's Judge gate
        # section (2026-07-27) — LATEST evaluation_round only per
        # (variant, judge_model), since reflexion re-scores a retried variant
        # and both rounds' rows persist (see migration 010).
        judge_scores_result = await conn.execute(
            text(
                """
                WITH latest_variants AS (
                    SELECT DISTINCT ON (task_id) id, task_id
                    FROM content_variants
                    WHERE campaign_id = :campaign_id
                    ORDER BY task_id, created_at DESC
                ),
                ranked AS (
                    SELECT
                        bs.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY bs.variant_id, bs.judge_model
                            ORDER BY bs.evaluation_round DESC
                        ) AS rn
                    FROM brand_scores bs
                    JOIN latest_variants lv ON lv.id = bs.variant_id
                )
                SELECT variant_id, judge_model, composite_score, scores, critical_violations
                FROM ranked
                WHERE rn = 1
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        judge_score_rows = judge_scores_result.mappings().all()

        cost_by_agent = await _load_cost_attribution(normalized_campaign_id)

    # 2026-07-29: campaigns.token_cost_usd was not rolled up on the draft
    # path (persist_draft_batch only set status), so all campaigns showed $0.
    # cost_by_agent is already loaded from campaign_cost_attribution above —
    # use it as the authoritative source. Fall back to the campaigns column
    # for older rows written before this fix.
    attribution_total = sum(
        entry["cost_usd"] or 0.0
        for entries in cost_by_agent.values()
        for entry in entries
    )
    reported_cost = attribution_total if attribution_total > 0 else float(campaign_row["token_cost_usd"])
    return {
        "id": str(campaign_row["id"]),
        "org_id": str(campaign_row["org_id"]),
        "brand_id": str(campaign_row["brand_id"]),
        "status": str(campaign_row["status"]),
        "token_cost_usd": reported_cost,
        "created_at": campaign_row["created_at"],
        "started_at": campaign_row["started_at"],
        "completed_at": campaign_row["completed_at"],
        "brief": campaign_row["brief"] or {},
        "created_by": str(campaign_row["created_by"]) if campaign_row["created_by"] else None,
        "creator_email": campaign_row["creator_email"],
        "conversation_id": str(conversation_row["id"]) if conversation_row else None,
        "in_memory_trace": in_memory_trace,
        "cost_by_agent": cost_by_agent,
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
                "translation_engine": row["translation_engine"],
                "back_translation_score": (
                    float(row["back_translation_score"])
                    if row["back_translation_score"] is not None
                    else None
                ),
                "failure_reason": row["failure_reason"],
                "translation_checks": row["translation_checks"],
                # Per-judge score/reasoning for this variant — Run summary
                # panel's Judge gate section (2026-07-27).
                "judge_scores": [
                    {
                        "judge_model": jr["judge_model"],
                        "composite_score": float(jr["composite_score"]),
                        "reasoning": _summarise_judge_reasoning(jr["scores"]),
                        "critical_violations": list(jr["critical_violations"] or []),
                    }
                    for jr in judge_score_rows
                    if jr["variant_id"] == row["id"]
                ],
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


@router.get("/{campaign_id}/events/replay")
async def replay_campaign_events(
    campaign_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
    before_event_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)
    timeline = await _load_in_memory_trace(normalized_campaign_id)
    all_events = _trace_to_replay_events(normalized_campaign_id, timeline)
    events, has_more, cursor_found = _window_replay_events(
        all_events,
        limit=limit,
        before_event_id=before_event_id,
    )
    return {
        "campaign_id": normalized_campaign_id,
        "events": events,
        "cursor_found": cursor_found,
        "has_more": has_more,
        "next_before_event_id": events[0]["event_id"] if has_more and events else None,
        "last_event_id": events[-1]["event_id"] if events else None,
    }


@router.get("/{campaign_id}/stream")
async def stream_campaign_events(campaign_id: str) -> StreamingResponse:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)
    channel = f"campaign:{normalized_campaign_id}:events"
    redis = get_redis()

    async def event_stream() -> AsyncIterator[str]:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield ": connected\n\n"
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message and message.get("type") == "message":
                    payload = _message_payload_to_text(message)
                    try:
                        payload = _normalize_live_stream_payload(normalized_campaign_id, payload)
                    except Exception:  # noqa: BLE001
                        pass
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{campaign_id}/rerun")
async def rerun_campaign(
    campaign_id: str,
    body: RerunCampaignRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    normalized_campaign_id = _normalize_campaign_id(campaign_id)

    async with get_db() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, org_id, brand_id
                FROM campaigns
                WHERE id = :campaign_id
                """
            ),
            {"campaign_id": normalized_campaign_id},
        )
        row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMPAIGN_NOT_FOUND)

    campaign_org_id = str(row["org_id"])
    campaign_brand_id = str(row["brand_id"])
    if campaign_org_id != user.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="campaign does not belong to org")
    if user.brand_ids and campaign_brand_id not in user.brand_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="brand access denied")

    try:
        result = await rerun_service.rerun_campaign(
            campaign_id=normalized_campaign_id,
            resume_from_node=body.resume_from_node,
            requested_by=user.user_id,
            trigger=body.trigger,
            user_edit=body.user_edit,
            variant_task_id=body.variant_task_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return result
