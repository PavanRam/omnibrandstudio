from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from opentelemetry.propagate import inject
from pydantic import BaseModel
from sqlalchemy import text

from api.deps import UserContext, get_current_user
from api.middleware.auth import decode_access_token, is_jti_revoked
from core.config import settings
from core.ids import new_campaign_id, new_request_id
from core.redis import get_redis
from pipeline.conversation_models import ConversationPlannerInput, ConversationSession, ExtractionMeta, IntentClassification, PartialBrief
from services.chat.brief_collector import brief_collector
from services.campaign.campaign_query import get_recent_campaigns
from services.chat.conversation_planner import conversation_planner
from services.chat.conversation_responder import conversation_responder
from services.chat.intent_classifier import intent_classifier
from services.chat.session_manager import session_manager

router = APIRouter()

QUEUE = "campaigns:queue"


class CreateConversationRequest(BaseModel):
    brand_id: str


def _normalize_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field_name} must be a valid UUID",
        ) from exc


def _optional_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _assert_brand_access(user: UserContext, brand_id: str) -> None:
    if user.brand_ids and brand_id not in user.brand_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="brand access denied")


def _resolve_ws_api_key(websocket: WebSocket, payload: dict[str, Any], query_api_key: str | None) -> str:
    api_key = websocket.headers.get("x-api-key") or query_api_key or payload.get("api_key")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing x-api-key header")
    return str(api_key)


async def _resolve_ws_user(
    websocket: WebSocket,
    payload: dict[str, Any],
    query_api_key: str | None,
    query_access_token: str | None,
) -> UserContext:
    authorization_header = websocket.headers.get("authorization") or str(payload.get("authorization") or "")
    bearer_token = ""
    if authorization_header.lower().startswith("bearer "):
        bearer_token = authorization_header[7:].strip()
    elif query_access_token:
        bearer_token = query_access_token
    elif payload.get("access_token"):
        bearer_token = str(payload.get("access_token"))

    if bearer_token:
        try:
            claims = decode_access_token(bearer_token)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

        jti = claims.get("jti")
        if isinstance(jti, str) and await is_jti_revoked(jti):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")

        return UserContext(
            user_id=str(claims.get("sub") or ""),
            org_id=str(claims.get("org_id") or ""),
            brand_ids=[str(value) for value in claims.get("brand_ids", [])],
            roles=[str(value) for value in claims.get("roles", [])],
            auth_method="jwt",
        )

    api_key = websocket.headers.get("x-api-key") or query_api_key or payload.get("api_key")
    if api_key:
        from api.deps import _authenticate_api_key

        return await _authenticate_api_key(str(api_key))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing credentials",
    )


def _chat_state_context(session: ConversationSession) -> dict[str, Any]:
    return {
        "campaign_id": session.active_campaign_id,
        "org_id": session.org_id,
        "brand_id": session.brand_id,
        "request_id": new_request_id(),
        "model_aliases": {
            "utility": "util-fast",
            "brief_collector": "brief-collector",
            "responder": "responder-chat",
        },
    }


def _is_simple_greeting(message: str) -> bool:
    normalized = " ".join(message.lower().strip().split())
    greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "hiya",
        "good morning",
        "good afternoon",
        "good evening",
    }
    return normalized in greetings


def _complete_brief_followup(user_message: str) -> str:
    lowered = user_message.lower().strip()

    if _is_simple_greeting(user_message):
        return (
            "Hey. Your brief is complete and ready to run. "
            "Say 'run campaign' when you want to start, or ask me to recap the brief first."
        )

    if "thank" in lowered:
        return (
            "Anytime. Your brief is ready. "
            "Say 'run campaign' to start execution, or ask for status/history help."
        )

    if any(phrase in lowered for phrase in ("what can you", "help", "options", "next")):
        return (
            "Your brief is complete. I can help you with three quick actions: "
            "1) run campaign, 2) check campaign status, 3) show agent outputs. "
            "Tell me which one you want."
        )

    return (
        "Your brief is complete. Say 'run campaign' to start execution, "
        "or ask me to recap the brief before running."
    )


def _build_planner_output(
    *,
    user_message: str,
    intent: str,
    brief: PartialBrief,
    previous_brief: PartialBrief,
    brief_changes: list[dict[str, Any]],
    history: list[dict[str, str]],
    active_campaign_id: str | None,
    intent_classification: IntentClassification | None = None,
    field_confidence: dict[str, float] | None = None,
):
    if not settings.ENABLE_CONVERSATION_PLANNER:
        return None

    return conversation_planner.plan(
        ConversationPlannerInput(
            user_message=user_message,
            intent=intent,
            brief=brief,
            conversation_history=history,
            active_campaign_id=active_campaign_id,
            previous_brief=previous_brief,
            brief_changes=brief_changes,
            intent_classification=intent_classification,
            field_confidence=field_confidence or {},
        )
    )


def _select_assistant_message(
    *,
    campaign_id: str | None,
    campaign_copilot_message: str | None,
    brief: PartialBrief,
    previous_brief: PartialBrief,
    user_message: str,
    planner_output,
) -> str:
    if campaign_id:
        return (
            "Campaign queued successfully. "
            f"Campaign ID: {campaign_id}. You can subscribe to /campaigns/{campaign_id}/stream."
        )

    if campaign_copilot_message:
        return campaign_copilot_message

    if planner_output and planner_output.reply_strategy == "greeting":
        return planner_output.next_question or (
            "Hey, great to collaborate on this. "
            "What are you launching, and who do you most want to reach first?"
        )

    if brief.is_complete():
        return _complete_brief_followup(user_message)

    if planner_output and planner_output.next_question:
        return _planner_followup_message(previous_brief, brief, planner_output)

    return brief_collector.next_question(brief)


def _planner_followup_message(previous_brief: PartialBrief, current_brief: PartialBrief, planner_output) -> str:
    updates = _brief_updates(previous_brief, current_brief)
    if updates:
        if len(updates) == 1:
            acknowledgement = f"Great, I captured {updates[0]}."
        else:
            acknowledgement = f"Great, I captured {', '.join(updates[:-1])}, and {updates[-1]}."
    elif planner_output.correction_detected:
        acknowledgement = "Got it, I applied that update to your brief."
    else:
        acknowledgement = "Thanks, that helps."

    return f"{acknowledgement} {planner_output.next_question}".strip()


def _brief_updates(previous_brief: PartialBrief, current_brief: PartialBrief) -> list[str]:
    updates: list[str] = []

    if _is_new_scalar(previous_brief.objective, current_brief.objective):
        updates.append("the campaign objective")
    if _is_new_scalar(previous_brief.target_audience, current_brief.target_audience):
        updates.append("the target audience")
    if _is_new_scalar(previous_brief.tone_override, current_brief.tone_override):
        updates.append("the tone")
    if _is_new_budget(previous_brief.token_budget, current_brief.token_budget):
        updates.append("the budget guardrail")

    if _has_new_values(previous_brief.channels, current_brief.channels):
        updates.append("the channels")
    if _has_new_values(previous_brief.locales, current_brief.locales):
        updates.append("the locales")
    if _has_new_values(previous_brief.audience_segments, current_brief.audience_segments):
        updates.append("the audience segments")
    if _has_new_values(previous_brief.key_messages, current_brief.key_messages):
        updates.append("key messaging")

    return updates


def _brief_changes(previous_brief: PartialBrief, current_brief: PartialBrief) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for field in ("objective", "target_audience", "tone_override", "token_budget"):
        before = getattr(previous_brief, field)
        after = getattr(current_brief, field)
        if before == after:
            continue
        changes.append(
            {
                "field": field,
                "change_type": _change_type_scalar(before, after),
                "before": before,
                "after": after,
            }
        )

    for field in ("channels", "locales", "audience_segments", "key_messages"):
        before_list = list(getattr(previous_brief, field))
        after_list = list(getattr(current_brief, field))
        if _norm_list(before_list) == _norm_list(after_list):
            continue
        changes.append(
            {
                "field": field,
                "change_type": _change_type_list(before_list, after_list),
                "before": before_list,
                "after": after_list,
            }
        )

    return changes


def _is_new_scalar(previous: str | None, current: str | None) -> bool:
    before = (previous or "").strip()
    after = (current or "").strip()
    return bool(after) and before != after


def _is_new_budget(previous: int | None, current: int | None) -> bool:
    return bool(current and current > 0 and previous != current)


def _has_new_values(previous: list[str], current: list[str]) -> bool:
    before = {v.strip().lower() for v in previous if v and v.strip()}
    after = {v.strip().lower() for v in current if v and v.strip()}
    return bool(after - before)


def _change_type_scalar(before: Any, after: Any) -> str:
    if _is_empty_value(before) and not _is_empty_value(after):
        return "added"
    if not _is_empty_value(before) and _is_empty_value(after):
        return "removed"
    return "replaced"


def _change_type_list(before: list[str], after: list[str]) -> str:
    if not _norm_list(before) and _norm_list(after):
        return "added"
    if _norm_list(before) and not _norm_list(after):
        return "removed"
    return "replaced"


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _norm_list(values: list[str]) -> set[str]:
    return {v.strip().lower() for v in values if isinstance(v, str) and v.strip()}


async def _process_turn(
    *,
    session: ConversationSession,
    conversation_id: str,
    user: UserContext,
    user_message: str,
) -> dict[str, Any]:
    await session_manager.add_message(conversation_id, "user", user_message)

    history = await session_manager.load_messages(conversation_id)
    context = _chat_state_context(session)
    intent_classification = await _classify_intent_with_fallback(
        user_message=user_message,
        history=history,
        context=context,
    )
    intent = intent_classification.primary

    previous_brief = session.partial_brief
    brief, extraction_meta = await _collect_brief_with_meta(
        previous_brief=previous_brief,
        user_message=user_message,
        context=context,
    )

    await session_manager.update_partial_brief(conversation_id, brief)
    brief_changes = _brief_changes(previous_brief, brief)

    planner_output = _build_planner_output(
        user_message=user_message,
        intent=intent,
        brief=brief,
        previous_brief=previous_brief,
        brief_changes=brief_changes,
        history=history,
        active_campaign_id=session.active_campaign_id,
        intent_classification=intent_classification,
        field_confidence=extraction_meta.field_confidence,
    )
    brief_updates = _brief_updates(previous_brief, brief)

    should_run = ("run" in user_message.lower() and "campaign" in user_message.lower()) or intent == "submit_campaign"
    campaign_id: str | None = None
    campaign_copilot_message: str | None = None

    if intent in {"check_status", "explain_progress", "show_agent_output", "view_history"}:
        campaign_copilot_message = await _campaign_copilot_reply(
            conversation_id=conversation_id,
            session=session,
            intent=intent,
            user_message=user_message,
        )

    if should_run and brief.is_complete():
        campaign_id = await _enqueue_campaign(
            user=user,
            brand_id=session.brand_id,
            brief=brief,
            request_id=new_request_id(),
        )
        await session_manager.attach_campaign(conversation_id, campaign_id)

    assistant_message = await _compose_assistant_message(
        campaign_id=campaign_id,
        campaign_copilot_message=campaign_copilot_message,
        brief=brief,
        previous_brief=previous_brief,
        user_message=user_message,
        planner_output=planner_output,
        brief_changes=brief_changes,
        context=context,
    )

    await session_manager.add_message(
        conversation_id,
        "assistant",
        assistant_message,
        intent_classified=intent,
        campaign_id=campaign_id,
    )

    return {
        "conversation_id": conversation_id,
        "intent": intent,
        "brief": brief.model_dump(),
        "brief_complete": brief.is_complete(),
        "campaign_id": campaign_id,
        "message": assistant_message,
        "brief_updates": brief_updates,
        "brief_changes": brief_changes,
        "conversation_stage": planner_output.stage if planner_output else None,
        "planner_objective": planner_output.objective if planner_output else None,
        "primary_objective": planner_output.primary_objective if planner_output else None,
        "secondary_objectives": planner_output.secondary_objectives if planner_output else [],
        "turn_type": planner_output.turn_type if planner_output else None,
        "needs_clarification": planner_output.needs_clarification if planner_output else False,
        "clarification_target": planner_output.clarification_target if planner_output else None,
        "brief_field_states": [state.model_dump() for state in planner_output.brief_field_states] if planner_output else [],
        "suggested_prompts": planner_output.suggested_prompts if planner_output else [],
        "correction_detected": planner_output.correction_detected if planner_output else False,
    }


async def _classify_intent_with_fallback(
    *,
    user_message: str,
    history: list[dict[str, str]],
    context: dict[str, Any],
) -> IntentClassification:
    try:
        return await intent_classifier.classify_detailed(
            message=user_message,
            conversation_history=history,
            state=context,
        )
    except Exception:
        intent = await intent_classifier.classify(
            message=user_message,
            conversation_history=history,
            state=context,
        )
        return IntentClassification(primary=intent, secondary=[], confidence=0.0)


async def _collect_brief_with_meta(
    *,
    previous_brief: PartialBrief,
    user_message: str,
    context: dict[str, Any],
) -> tuple[PartialBrief, ExtractionMeta]:
    try:
        return await brief_collector.update_partial_brief_with_meta(
            current=previous_brief,
            user_message=user_message,
            state=context,
        )
    except Exception:
        brief = await brief_collector.update_partial_brief(
            current=previous_brief,
            user_message=user_message,
            state=context,
        )
        return brief, ExtractionMeta(field_confidence={}, source="fallback")


async def _compose_assistant_message(
    *,
    campaign_id: str | None,
    campaign_copilot_message: str | None,
    brief: PartialBrief,
    previous_brief: PartialBrief,
    user_message: str,
    planner_output,
    brief_changes: list[dict[str, Any]],
    context: dict[str, Any],
) -> str:
    if campaign_id:
        return (
            "Campaign queued successfully. "
            f"Campaign ID: {campaign_id}. You can subscribe to /campaigns/{campaign_id}/stream."
        )

    if campaign_copilot_message:
        return campaign_copilot_message

    if settings.ENABLE_CONVERSATION_PLANNER and planner_output:
        return await conversation_responder.respond(
            planner_output=planner_output,
            brief=brief,
            brief_changes=brief_changes,
            user_message=user_message,
            state=context,
        )

    return _select_assistant_message(
        campaign_id=campaign_id,
        campaign_copilot_message=campaign_copilot_message,
        brief=brief,
        previous_brief=previous_brief,
        user_message=user_message,
        planner_output=planner_output,
    )


async def _campaign_copilot_reply(
    *,
    conversation_id: str,
    session: ConversationSession,
    intent: str,
    user_message: str,
) -> str | None:
    campaign_id = session.active_campaign_id
    if not campaign_id:
        return (
            "No active campaign is attached to this conversation yet. "
            "Finish the brief and send 'run campaign' to start one."
        )

    from core.database import get_db

    async with get_db() as conn:
        campaign_result = await conn.execute(
            text(
                """
                SELECT id, status, started_at, completed_at, token_cost_usd, created_at
                FROM campaigns
                WHERE id = :campaign_id
                """
            ),
            {"campaign_id": campaign_id},
        )
        campaign_row = campaign_result.mappings().first()

        if campaign_row is None:
            return (
                f"I could not find campaign {campaign_id}. "
                "Try refreshing the conversation list and selecting the latest session."
            )

        variants_result = await conn.execute(
            text(
                """
                SELECT status, COUNT(*) AS count
                FROM content_variants
                WHERE campaign_id = :campaign_id
                GROUP BY status
                ORDER BY status ASC
                """
            ),
            {"campaign_id": campaign_id},
        )
        variant_rows = variants_result.mappings().all()

    trace: list[dict[str, Any]] = []
    if intent in {"explain_progress", "show_agent_output", "view_history"}:
        trace = await _load_campaign_trace(campaign_id)

    summary = _campaign_summary(campaign_row, variant_rows, trace)

    if intent == "check_status":
        return _campaign_status_reply(campaign_id, campaign_row, summary)
    if intent == "explain_progress":
        return _campaign_progress_reply(campaign_id, summary)
    if intent == "show_agent_output":
        return _campaign_agent_output_reply(campaign_id, user_message, summary, trace)
    if intent == "view_history":
        return _campaign_history_reply(conversation_id, campaign_id, summary)
    return None


async def _load_campaign_trace(campaign_id: str) -> list[dict[str, Any]]:
    try:
        from api.routers import campaigns as campaigns_router

        return await campaigns_router._load_in_memory_trace(campaign_id)
    except Exception:
        return []


def _campaign_summary(
    campaign_row: dict[str, Any],
    variant_rows: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    status_value = str(campaign_row["status"])
    total_variants = int(sum(int(r["count"]) for r in variant_rows))
    variants_breakdown = ", ".join(f"{r['status']}: {r['count']}" for r in variant_rows) or "none yet"
    trace_phase = _latest_trace_phase(trace)
    recent_agents = _recent_trace_agents(trace)
    return {
        "status": status_value,
        "total_variants": total_variants,
        "variants_breakdown": variants_breakdown,
        "trace_phase": trace_phase,
        "recent_agents": recent_agents,
    }


def _campaign_status_reply(campaign_id: str, campaign_row: dict[str, Any], summary: dict[str, Any]) -> str:
    return (
        f"Campaign {campaign_id} is currently '{summary['status']}'. "
        f"Variants: {summary['total_variants']} ({summary['variants_breakdown']}). "
        f"Started: {campaign_row['started_at'] or 'not started'}, "
        f"Completed: {campaign_row['completed_at'] or 'not completed'}, "
        f"Cost: ${float(campaign_row['token_cost_usd']):.4f}."
    )


def _campaign_progress_reply(campaign_id: str, summary: dict[str, Any]) -> str:
    status_value = str(summary["status"])
    if status_value in {"queued", "running"}:
        progress_hint = "Execution is in progress; new events should appear in the campaign stream."
    elif status_value == "awaiting_review":
        progress_hint = "Pipeline reached review stage and is waiting for a human decision."
    elif status_value in {"published", "failed", "cancelled"}:
        progress_hint = "Pipeline reached a terminal state."
    else:
        progress_hint = "Campaign is active in a non-terminal state."

    return (
        f"Progress for campaign {campaign_id}: status '{status_value}'. "
        f"Current output footprint is {summary['total_variants']} variants ({summary['variants_breakdown']}). "
        f"{progress_hint}"
        f" Latest trace phase: {summary.get('trace_phase') or 'unavailable'}."
    )


def _campaign_agent_output_reply(
    campaign_id: str,
    user_message: str,
    summary: dict[str, Any],
    trace: list[dict[str, Any]],
) -> str:
    requested_agent = _extract_requested_agent(user_message)
    if requested_agent:
        trace_line = _agent_trace_line(trace, requested_agent)
        if trace_line:
            return (
                f"Campaign {campaign_id} latest {requested_agent} output: {trace_line}. "
                f"Overall status is '{summary['status']}' with {summary['total_variants']} variants."
            )
        return (
            f"For {requested_agent}, open the campaign stream panel and filter by agent. "
            f"I can confirm campaign {campaign_id} status is '{summary['status']}' "
            f"with {summary['total_variants']} variants so far."
        )
    return (
        "Tell me which agent output you want (for example: content_generator, personalization_agent, or judge_claude), "
        "and I will summarize the latest campaign state around that step."
    )


def _campaign_history_reply(conversation_id: str, campaign_id: str, summary: dict[str, Any]) -> str:
    recent_agents = summary.get("recent_agents") or []
    recent_agents_text = ", ".join(recent_agents) if recent_agents else "none recorded"
    return (
        f"Conversation {conversation_id} is bound to campaign {campaign_id}. "
        f"Latest campaign status is '{summary['status']}' with {summary['total_variants']} "
        f"variants ({summary['variants_breakdown']}). "
        f"Recent traced agents: {recent_agents_text}. "
        "Use the campaign stream panel to inspect replay and live events in order."
    )


def _extract_requested_agent(user_message: str) -> str | None:
    requested = user_message.lower()
    for agent_name in (
        "content_generator",
        "personalization_agent",
        "translation_agent",
        "judge_claude",
        "judge_gpt4o",
        "judge_llama",
        "confidence_aggregator",
        "review_gate",
        "publishing_agent",
    ):
        if agent_name.replace("_", " ") in requested or agent_name in requested:
            return agent_name
    return None


def _latest_trace_phase(trace: list[dict[str, Any]]) -> str | None:
    if not trace:
        return None
    latest = trace[-1]
    state = latest.get("state") or {}
    phase = state.get("current_phase")
    return str(phase) if phase else None


def _recent_trace_agents(trace: list[dict[str, Any]]) -> list[str]:
    if not trace:
        return []
    agents: list[str] = []
    for step in trace[-4:]:
        for agent in step.get("agents") or []:
            if agent not in agents:
                agents.append(agent)
    return agents


def _agent_trace_line(trace: list[dict[str, Any]], agent: str) -> str | None:
    for step in reversed(trace):
        agents = step.get("agents") or []
        if agent not in agents:
            continue
        return _describe_agent_trace_step(step, agent)
    return None


def _describe_agent_trace_step(step: dict[str, Any], agent: str) -> str:
    state = step.get("state") or {}
    phase = str(state.get("current_phase") or "update")
    output = (step.get("agent_output") or {}).get(agent)

    output_line = _output_line_from_agent_output(output)
    if output_line:
        return f"phase '{phase}', {output_line}"

    variant_count = state.get("variant_count")
    if isinstance(variant_count, int):
        return f"phase '{phase}', total variants {variant_count}"
    return f"phase '{phase}'"


def _output_line_from_agent_output(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    errors = output.get("errors")
    if isinstance(errors, list) and errors:
        return f"error: {errors[0]}"
    variants = output.get("variants")
    if isinstance(variants, list):
        return f"variants delta {len(variants)}"
    return None


async def _enqueue_campaign(
    *,
    user: UserContext,
    brand_id: str,
    brief: PartialBrief,
    request_id: str,
) -> str:
    campaign_id = new_campaign_id()

    brief_payload = {
        "brand_id": brand_id,
        "objective": brief.objective or "",
        "target_audience": brief.target_audience or "",
        "key_messages": brief.key_messages,
        "tone_override": brief.tone_override,
        "channels": brief.channels,
        "locales": brief.locales,
        "audience_segments": brief.audience_segments,
        "token_budget": brief.token_budget or 0,
        "raw_text": brief.raw_text,
    }

    from core.database import get_db

    async with get_db() as conn:
        brand_result = await conn.execute(
            text(
                """
                SELECT id
                FROM brands
                WHERE id = :brand_id AND org_id = :org_id
                """
            ),
            {
                "brand_id": brand_id,
                "org_id": user.org_id,
            },
        )
        if brand_result.mappings().first() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="brand not found")

        await conn.execute(
            text(
                """
                INSERT INTO campaigns (id, org_id, brand_id, created_by, brief, status)
                VALUES (:id, :org_id, :brand_id, :created_by, CAST(:brief AS JSONB), :status)
                """
            ),
            {
                "id": campaign_id,
                "org_id": user.org_id,
                "brand_id": brand_id,
                "created_by": _optional_uuid(user.user_id),
                "brief": json.dumps(brief_payload),
                "status": "queued",
            },
        )
        await conn.commit()

    task = {
        "campaign_id": campaign_id,
        "org_id": user.org_id,
        "brand_id": brand_id,
        "user_id": user.user_id,
        "request_id": request_id,
        "brief": brief_payload,
    }
    trace_carrier: dict[str, str] = {}
    inject(trace_carrier)
    task["_trace_context"] = trace_carrier

    await get_redis().lpush(QUEUE, json.dumps(task))
    return campaign_id


@router.post("/conversations")
async def create_conversation(
    body: CreateConversationRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> ConversationSession:
    brand_id = _normalize_uuid(body.brand_id, "brand_id")
    _assert_brand_access(user, brand_id)
    return await session_manager.create(
        org_id=user.org_id,
        brand_id=brand_id,
        created_by=_optional_uuid(user.user_id),
    )


@router.get("/me/recent-campaigns")
async def recent_campaigns(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    campaigns = await get_recent_campaigns(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=_optional_uuid(user.user_id),
        limit=12,
    )
    return {"campaigns": [c.model_dump() for c in campaigns]}


@router.get("/users/me/recent-campaigns")
async def recent_campaigns_compat(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    campaigns = await get_recent_campaigns(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=_optional_uuid(user.user_id),
        limit=12,
    )
    return {"campaigns": [c.model_dump() for c in campaigns]}


@router.get("/me/recent-conversations")
async def recent_conversations(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    conversations_list = await session_manager.list_recent(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=_optional_uuid(user.user_id),
        limit=12,
    )
    return {"conversations": [c.model_dump() for c in conversations_list]}


@router.get("/users/me/recent-conversations")
async def recent_conversations_compat(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    conversations_list = await session_manager.list_recent(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=_optional_uuid(user.user_id),
        limit=12,
    )
    return {"conversations": [c.model_dump() for c in conversations_list]}


@router.get("/users/{user_id}/recent-conversations")
async def recent_conversations_by_user(
    user_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    # Current auth model supports "self" access only for this endpoint.
    if user_id != "me" and user_id != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user access denied")

    conversations_list = await session_manager.list_recent(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=_optional_uuid(user.user_id),
        limit=12,
    )
    return {"conversations": [c.model_dump() for c in conversations_list]}


@router.websocket("/conversations/{conversation_id}")
async def conversation_ws(websocket: WebSocket, conversation_id: str) -> None:
    await websocket.accept()
    query_api_key = websocket.query_params.get("api_key")
    query_access_token = websocket.query_params.get("access_token")
    normalized_id = _normalize_uuid(conversation_id, "conversation_id")

    try:
        while True:
            payload = await websocket.receive_json()
            user_message = str(payload.get("message", "")).strip()
            if not user_message:
                await websocket.send_json({"error": "message is required"})
                continue

            try:
                user = await _resolve_ws_user(
                    websocket,
                    payload,
                    query_api_key,
                    query_access_token,
                )
            except HTTPException as exc:
                await websocket.send_json({"error": exc.detail})
                continue

            session = await session_manager.get(normalized_id)
            if session is None:
                await websocket.send_json({"error": "conversation not found"})
                continue

            _assert_brand_access(user, session.brand_id)
            response_payload = await _process_turn(
                session=session,
                conversation_id=normalized_id,
                user=user,
                user_message=user_message,
            )

            await websocket.send_json(response_payload)

    except WebSocketDisconnect:
        return
