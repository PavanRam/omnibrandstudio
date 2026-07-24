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
from pipeline.conversation_models import ConversationPlannerInput, ConversationSession, ExtractionMeta, IntentClassification, PartialBrief, UnderstandingResult
from services.chat.brief_collector import brief_collector
from services.campaign.campaign_query import get_recent_campaigns
from services.chat.conversation_planner import conversation_planner
from services.chat.conversation_responder import conversation_responder
from services.chat.session_manager import session_manager
from services.chat.understanding_engine import understanding_engine
from services import review_service

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
            "understanding": "understanding",
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


def _brief_playback_message(brief: PartialBrief) -> str:
    lines = ["Here's the campaign brief I've captured:"]
    lines.append(f"- Objective: {brief.objective or '(none)'}")
    if brief.target_audience:
        lines.append(f"- Target audience: {brief.target_audience}")
    lines.append(f"- Channels: {', '.join(brief.channels) or '(none)'}")
    lines.append(f"- Locales: {', '.join(brief.locales) or '(none)'}")
    lines.append(f"- Audience segments: {', '.join(brief.audience_segments) or '(none)'}")
    if brief.key_messages:
        lines.append(f"- Key messages: {', '.join(brief.key_messages)}")
    if brief.tone_override:
        lines.append(f"- Tone: {brief.tone_override}")
    lines.append(f"- Token budget: {brief.token_budget or '(none)'}")
    lines.append("")
    lines.append(
        "Shall I run the campaign with this? Reply 'yes' to start, or tell me what to change."
    )
    return "\n".join(lines)


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
    understanding = await _understand_turn(
        previous_brief=session.partial_brief,
        user_message=user_message,
        history=history,
        context=context,
    )
    intent_classification = understanding.intent
    intent = intent_classification.primary

    previous_brief = session.partial_brief
    brief = understanding.brief
    extraction_meta = understanding.extraction_meta

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

    campaign_id: str | None = None
    campaign_summary_payload: dict[str, Any] | None = None

    copilot_context = await _resolve_campaign_turn_context(
        conversation_id=conversation_id,
        session=session,
        intent=intent,
        user_message=user_message,
    )
    campaign_copilot_message = copilot_context["campaign_copilot_message"]
    pending_reviews = copilot_context["pending_reviews"]

    # ── Confirmation gate ────────────────────────────────────────────────
    # A complete brief is NOT enqueued immediately. The assistant first plays
    # the brief back and waits; the campaign runs only after the user confirms.
    gate = _confirmation_gate_decision(
        brief=brief,
        session=session,
        user_message=user_message,
        intent=intent,
        campaign_copilot_message=campaign_copilot_message,
    )
    confirm_playback = bool(gate["confirm_playback"])

    campaign_id = await _apply_confirmation_gate(
        gate=gate,
        conversation_id=conversation_id,
        user=user,
        session=session,
        brief=brief,
    )

    # A recap request should play the captured brief back to the user. The
    # responder produces a natural LLM summary and falls back to a deterministic
    # playback if the model call fails, so a recap never loops on the submit
    # prompt. Skip when a campaign just started or a copilot reply already applies.
    if _is_recap_request(user_message) and not campaign_id and not campaign_copilot_message:
        confirm_playback = True

    assistant_message = await _compose_assistant_message(
        campaign_id=campaign_id,
        campaign_copilot_message=campaign_copilot_message,
        brief=brief,
        previous_brief=previous_brief,
        user_message=user_message,
        planner_output=planner_output,
        brief_changes=brief_changes,
        context=context,
        confirm_playback=confirm_playback,
    )

    active_campaign_for_summary = campaign_id or session.active_campaign_id
    campaign_summary_payload = await _load_campaign_summary_payload_safe(active_campaign_for_summary)

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
        "awaiting_confirmation": confirm_playback,
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
        "pending_reviews": pending_reviews,
        "campaign_summary": campaign_summary_payload,
    }


async def _resolve_campaign_turn_context(
    *,
    conversation_id: str,
    session: ConversationSession,
    intent: str,
    user_message: str,
) -> dict[str, Any]:
    campaign_copilot_message: str | None = None
    pending_reviews: list[dict[str, Any]] = []

    if intent in {"check_status", "explain_progress", "show_agent_output", "view_history"}:
        campaign_copilot_message = await _campaign_copilot_reply(
            conversation_id=conversation_id,
            session=session,
            intent=intent,
            user_message=user_message,
        )
    elif intent == "list_reviews" and session.active_campaign_id:
        pending_reviews = await _fetch_pending_reviews(session.active_campaign_id)
        campaign_copilot_message = _pending_reviews_message(pending_reviews)
    elif session.active_campaign_id and _is_explicit_run(user_message, intent):
        # A campaign is already attached; an explicit "run campaign" cannot start
        # another. Tell the user clearly instead of looping on the submit prompt.
        pending_reviews = await _fetch_pending_reviews(session.active_campaign_id)
        campaign_copilot_message = (
            f"A campaign is already running for this conversation (id {session.active_campaign_id}). "
            "Ask me for its status, or start a new conversation to launch another campaign."
        )
    elif session.active_campaign_id:
        # Surface pending reviews automatically whenever the active campaign
        # is paused for review, regardless of what the user asked about.
        pending_reviews = await _fetch_pending_reviews(session.active_campaign_id)

    return {
        "campaign_copilot_message": campaign_copilot_message,
        "pending_reviews": pending_reviews,
    }


def _confirmation_gate_decision(
    *,
    brief: PartialBrief,
    session: ConversationSession,
    user_message: str,
    intent: str,
    campaign_copilot_message: str | None,
) -> dict[str, Any]:
    brief_complete = brief.is_complete()
    was_awaiting = session.status == "awaiting_confirmation"
    explicit_run = _is_explicit_run(user_message, intent)
    affirmative = _is_affirmative(user_message)

    should_run = False
    confirm_playback = False
    if brief_complete and not session.active_campaign_id and not campaign_copilot_message:
        # Explicit "run campaign" (or a submit intent) starts immediately in a
        # single step. A bare affirmative only runs when we already asked the
        # user to confirm on a previous turn.
        should_run = bool(explicit_run or (was_awaiting and affirmative))
        confirm_playback = not should_run

    return {
        "brief_complete": brief_complete,
        "was_awaiting": was_awaiting,
        "should_run": should_run,
        "confirm_playback": confirm_playback,
    }


async def _apply_confirmation_gate(
    *,
    gate: dict[str, Any],
    conversation_id: str,
    user: UserContext,
    session: ConversationSession,
    brief: PartialBrief,
) -> str | None:
    if gate["should_run"]:
        campaign_id = await _enqueue_campaign(
            user=user,
            brand_id=session.brand_id,
            brief=brief,
            request_id=new_request_id(),
        )
        await session_manager.attach_campaign(conversation_id, campaign_id)
        return campaign_id

    if gate["confirm_playback"]:
        if not gate["was_awaiting"]:
            await session_manager.set_status(conversation_id, "awaiting_confirmation")
        return None

    if gate["was_awaiting"] and not gate["brief_complete"]:
        # User edited the brief back into an incomplete state; resume collecting.
        await session_manager.set_status(conversation_id, "collecting")
    return None


async def _load_campaign_summary_payload_safe(
    campaign_id: str | None,
) -> dict[str, Any] | None:
    if not campaign_id:
        return None
    try:
        return await _load_campaign_summary_payload(campaign_id)
    except Exception:
        return None


async def _understand_turn(
    *,
    previous_brief: PartialBrief,
    user_message: str,
    history: list[dict[str, str]],
    context: dict[str, Any],
) -> UnderstandingResult:
    try:
        return await understanding_engine.understand(
            current=previous_brief,
            user_message=user_message,
            conversation_history=history,
            state=context,
        )
    except Exception:
        # Degrade gracefully: keep the existing brief and mark intent unknown so
        # the turn still produces a safe conversational reply.
        merged = brief_collector._merge(previous_brief, {}, user_message)
        return UnderstandingResult(
            intent=IntentClassification(primary="other", secondary=[], confidence=0.0),
            brief=merged,
            extraction_meta=ExtractionMeta(field_confidence={}, source="error"),
        )


_AFFIRMATIVE_EXACT = {
    "yes",
    "yep",
    "yeah",
    "yup",
    "y",
    "confirm",
    "confirmed",
    "correct",
    "that's right",
    "thats right",
    "looks good",
    "lgtm",
    "go ahead",
    "go",
    "run it",
    "run",
    "start",
    "launch",
    "proceed",
    "do it",
    "sounds good",
    "ship it",
    "approve",
    "approved",
    "perfect",
    "ok run",
}


def _is_affirmative(message: str) -> bool:
    normalized = " ".join(message.lower().strip().split())
    trimmed = normalized.rstrip("!.")
    if trimmed in _AFFIRMATIVE_EXACT:
        return True
    if "campaign" in normalized and any(
        verb in normalized for verb in ("run", "start", "launch", "execute")
    ):
        return True
    return any(
        phrase in normalized
        for phrase in ("go ahead", "looks good", "confirm", "proceed", "run it", "ship it")
    )


def _is_explicit_run(message: str, intent: str) -> bool:
    """True when the user explicitly asks to run/launch the campaign."""
    normalized = message.lower()
    if intent == "submit_campaign":
        return True
    return "campaign" in normalized and any(
        verb in normalized for verb in ("run", "start", "launch", "execute", "kick off", "go")
    )


def _is_recap_request(message: str) -> bool:
    """True when the user asks to recap / summarize / read back the brief."""
    normalized = " ".join(message.lower().strip().split())
    if any(kw in normalized for kw in ("recap", "read back", "read it back", "recite")):
        return True
    if "brief" in normalized and any(
        w in normalized
        for w in ("summar", "show", "review", "go over", "what's in", "whats in", "remind")
    ):
        return True
    return False


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
    confirm_playback: bool = False,
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
            confirm_playback=confirm_playback,
        )

    if confirm_playback:
        return _brief_playback_message(brief)

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

    content_generator_preview: dict[str, Any] | None = None
    async with get_db() as conn:
        campaign_row = await _fetch_campaign_row(conn, campaign_id)

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

        if intent == "show_agent_output" and _extract_requested_agent(user_message) == "content_generator":
            preview_result = await conn.execute(
                text(
                    """
                    SELECT task_id, channel, locale, segment,
                           COALESCE(generated_content, personalized_content, final_content) AS content
                    FROM content_variants
                    WHERE campaign_id = :campaign_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"campaign_id": campaign_id},
            )
            preview_row = preview_result.mappings().first()
            content_generator_preview = dict(preview_row) if preview_row else None

    trace: list[dict[str, Any]] = []
    if intent in {"explain_progress", "show_agent_output", "view_history"}:
        trace = await _load_campaign_trace(campaign_id)

    summary = _campaign_summary(campaign_row, variant_rows, trace)

    if intent == "check_status":
        return _campaign_status_reply(campaign_id, campaign_row, summary)
    if intent == "explain_progress":
        return _campaign_progress_reply(campaign_id, summary)
    if intent == "show_agent_output":
        return _campaign_agent_output_reply(
            campaign_id,
            user_message,
            summary,
            trace,
            content_generator_preview,
        )
    if intent == "view_history":
        return _campaign_history_reply(conversation_id, campaign_id, summary)
    return None


async def _fetch_campaign_row(conn: Any, campaign_id: str) -> dict[str, Any] | None:
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
    row = campaign_result.mappings().first()
    return dict(row) if row else None


async def _load_campaign_summary_payload(campaign_id: str) -> dict[str, Any] | None:
    from core.database import get_db

    async with get_db() as conn:
        campaign_row = await _fetch_campaign_row(conn, campaign_id)
        token_usage = await _fetch_campaign_token_usage(conn, campaign_id)

    if campaign_row is None:
        return None

    updated_at = (
        campaign_row.get("completed_at")
        or campaign_row.get("started_at")
        or campaign_row.get("created_at")
    )
    updated_at_text = (
        updated_at.isoformat() if hasattr(updated_at, "isoformat") and updated_at is not None else None
    )
    return {
        "campaign_id": str(campaign_row["id"]),
        "status": str(campaign_row["status"]),
        "token_cost_usd": float(token_usage.get("cost_usd") or 0.0),
        "input_tokens": token_usage.get("input_tokens"),
        "output_tokens": token_usage.get("output_tokens"),
        "total_tokens": token_usage.get("total_tokens"),
        "updated_at": updated_at_text,
    }


async def _fetch_campaign_token_usage(conn: Any, campaign_id: str) -> dict[str, int | None]:
    try:
        result = await conn.execute(
            text(
                """
                SELECT
                    COALESCE(SUM(input_tokens), 0)::BIGINT AS input_tokens,
                    COALESCE(SUM(output_tokens), 0)::BIGINT AS output_tokens,
                    COALESCE(SUM(total_cost_usd), 0)::DOUBLE PRECISION AS cost_usd
                FROM campaign_cost_attribution
                WHERE campaign_id = CAST(:campaign_id AS UUID)
                """
            ),
            {"campaign_id": campaign_id},
        )
        row = result.mappings().first()
        if not row:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}

        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": float(row.get("cost_usd") or 0.0),
        }
    except Exception:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
        }


async def _fetch_pending_reviews(campaign_id: str) -> list[dict[str, Any]]:
    from core.database import get_db

    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT rr.id AS review_request_id, rr.variant_id, rr.campaign_id,
                           rr.routing_reason, rr.status, rr.sla_deadline, rr.scores_snapshot,
                           cv.task_id, cv.locale, cv.channel, cv.segment,
                           COALESCE(cv.final_content, cv.personalized_content,
                                    cv.generated_content) AS content,
                           a.weighted_mean AS composite_score
                    FROM review_requests rr
                    JOIN content_variants cv ON cv.id = rr.variant_id
                    LEFT JOIN aggregated_scores a ON a.variant_id = rr.variant_id
                    WHERE rr.status = 'pending' AND rr.campaign_id = CAST(:campaign_id AS UUID)
                    ORDER BY rr.created_at ASC
                    """
                ),
                {"campaign_id": campaign_id},
            )
        ).mappings().all()

    return [
        {
            "review_request_id": str(r["review_request_id"]),
            "variant_id": str(r["variant_id"]),
            "campaign_id": str(r["campaign_id"]),
            "task_id": r["task_id"],
            "locale": r["locale"],
            "channel": r["channel"],
            "segment": r["segment"],
            "status": r["status"],
            "routing_reason": r["routing_reason"],
            "sla_deadline": r["sla_deadline"].isoformat() if r["sla_deadline"] else None,
            "content": r["content"],
            "composite_score": (
                float(r["composite_score"]) if r["composite_score"] is not None else None
            ),
            "scores_snapshot": r["scores_snapshot"],
        }
        for r in rows
    ]


def _pending_reviews_message(reviews: list[dict[str, Any]]) -> str:
    if not reviews:
        return "No content is currently waiting on your review."
    lines = [f"{len(reviews)} variant(s) need your review before this campaign can publish:"]
    for review in reviews:
        score = review.get("composite_score")
        score_text = f"{score:.2f}" if isinstance(score, float) else "n/a"
        lines.append(
            f"- {review['task_id']} (score {score_text}) — {review.get('routing_reason') or 'flagged'}"
        )
    lines.append("Reply with the review card's Approve / Reject / Edit action to decide.")
    return "\n".join(lines)


async def _process_review_action(
    *,
    session: ConversationSession,
    conversation_id: str,
    user: UserContext,
    review_request_id: str,
    decision: str,
    reviewer_note: str | None,
    edited_content: str | None,
) -> dict[str, Any]:
    """Handle a structured approve/reject/edit action sent from a review card.

    This bypasses brief understanding entirely — the card already tells us
    exactly which review and which decision, so there is nothing to classify.
    """
    campaign_id = session.active_campaign_id
    user_summary = f"[review action] {decision} on {review_request_id}"
    await session_manager.add_message(conversation_id, "user", user_summary)

    try:
        result = await review_service.apply_decision(
            review_request_id,
            decision,
            reviewer_note,
            edited_content,
            actor_id=user.user_id,
            brand_ids=user.brand_ids,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        message = f"Could not record that decision: {exc}"
        await session_manager.add_message(conversation_id, "assistant", message, intent_classified="decide_review")
        return {
            "conversation_id": conversation_id,
            "intent": "decide_review",
            "message": message,
            "campaign_id": campaign_id,
            "error": str(exc),
        }

    if not result["all_decided"]:
        remaining = await _fetch_pending_reviews(result["campaign_id"])
        message = (
            f"Got it — recorded '{decision}' for {result['task_id']}. "
            f"{len(remaining)} more variant(s) still need a decision."
        )
        await session_manager.add_message(
            conversation_id, "assistant", message, intent_classified="decide_review", campaign_id=result["campaign_id"]
        )
        return {
            "conversation_id": conversation_id,
            "intent": "decide_review",
            "message": message,
            "campaign_id": result["campaign_id"],
            "campaign_status": "awaiting_review",
            "pending_reviews": remaining,
        }

    campaign_status = await review_service.resume_campaign(result["campaign_id"])
    if campaign_status == "published":
        message = f"All reviews are in — campaign {result['campaign_id']} has published."
    elif campaign_status == "awaiting_review":
        message = "Rejected content is regenerating; a new review round is ready when you are."
    else:
        message = f"Campaign {result['campaign_id']} is now '{campaign_status}'."

    pending_reviews = (
        await _fetch_pending_reviews(result["campaign_id"]) if campaign_status == "awaiting_review" else []
    )

    await session_manager.add_message(
        conversation_id, "assistant", message, intent_classified="decide_review", campaign_id=result["campaign_id"]
    )
    return {
        "conversation_id": conversation_id,
        "intent": "decide_review",
        "message": message,
        "campaign_id": result["campaign_id"],
        "campaign_status": campaign_status,
        "pending_reviews": pending_reviews,
    }


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
        "has_started": campaign_row.get("started_at") is not None,
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
    content_generator_preview: dict[str, Any] | None = None,
) -> str:
    requested_agent = _extract_requested_agent(user_message)
    has_started = bool(summary.get("has_started", True))

    if not requested_agent and not has_started:
        return (
            f"Campaign {campaign_id} has not started yet, so there are no agent outputs to show. "
            "Say 'run campaign' to start execution."
        )

    if requested_agent:
        trace_line = _agent_trace_line(trace, requested_agent)
        if requested_agent == "content_generator":
            content_reply = _content_generator_output_reply(
                campaign_id=campaign_id,
                summary=summary,
                has_started=has_started,
                trace_line=trace_line,
                content_generator_preview=content_generator_preview,
            )
            if content_reply:
                return content_reply

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


def _content_generator_output_reply(
    *,
    campaign_id: str,
    summary: dict[str, Any],
    has_started: bool,
    trace_line: str | None,
    content_generator_preview: dict[str, Any] | None,
) -> str | None:
    if not has_started:
        return (
            f"Campaign {campaign_id} has not started yet, so content_generator has no output yet. "
            "Say 'run campaign' to start execution."
        )

    preview_text = _content_preview_line(content_generator_preview)
    if preview_text:
        if trace_line:
            return (
                f"Campaign {campaign_id} latest content_generator output: {preview_text}. "
                f"Trace context: {trace_line}. Overall status is '{summary['status']}' "
                f"with {summary['total_variants']} variants."
            )
        return (
            f"Campaign {campaign_id} latest content_generator output: {preview_text}. "
            f"Overall status is '{summary['status']}' with {summary['total_variants']} variants."
        )

    if summary["total_variants"] == 0:
        return (
            f"Campaign {campaign_id} is '{summary['status']}', but content_generator has not produced "
            "a variant yet."
        )
    return None


def _content_preview_line(preview: dict[str, Any] | None) -> str | None:
    if not isinstance(preview, dict):
        return None

    content = str(preview.get("content") or "").strip()
    if not content:
        return None

    snippet = " ".join(content.split())
    if len(snippet) > 220:
        snippet = snippet[:217].rstrip() + "..."

    task_id = str(preview.get("task_id") or "").strip()
    channel = str(preview.get("channel") or "").strip()
    locale = str(preview.get("locale") or "").strip()
    segment = str(preview.get("segment") or "").strip()

    metadata = []
    if task_id:
        metadata.append(f"task {task_id}")
    if channel:
        metadata.append(channel)
    if locale:
        metadata.append(locale)
    if segment:
        metadata.append(segment)

    if metadata:
        return f"({', '.join(metadata)}) \"{snippet}\""
    return f"\"{snippet}\""


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
    requested = " ".join(user_message.lower().strip().split())
    if not requested:
        return None

    aliases: dict[str, tuple[str, ...]] = {
        "content_generator": ("content_generator", "content generator", "content gen", "generator"),
        "personalization_agent": ("personalization_agent", "personalization agent", "personalization"),
        "translation_agent": ("translation_agent", "translation agent", "translation"),
        "judge_claude": ("judge_claude", "judge claude", "claude judge"),
        "judge_gpt4o": ("judge_gpt4o", "judge gpt4o", "gpt4o judge", "gpt-4o judge"),
        "judge_llama": ("judge_llama", "judge llama", "llama judge"),
        "confidence_aggregator": (
            "confidence_aggregator",
            "confidence aggregator",
            "aggregator",
            "score aggregator",
        ),
        "review_gate": ("review_gate", "review gate", "review"),
        "publishing_agent": ("publishing_agent", "publishing agent", "publish", "publishing"),
    }

    best_agent: str | None = None
    best_score = 0
    for agent_name, tokens in aliases.items():
        score = 0
        for token in tokens:
            if token in requested:
                score = max(score, len(token))
        if score > best_score:
            best_score = score
            best_agent = agent_name

    if best_agent:
        return best_agent

    for agent_name in aliases:
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
            review_request_id = payload.get("review_request_id")
            user_message = str(payload.get("message", "")).strip()
            if not user_message and not review_request_id:
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

            if review_request_id:
                response_payload = await _process_review_action(
                    session=session,
                    conversation_id=normalized_id,
                    user=user,
                    review_request_id=str(review_request_id),
                    decision=str(payload.get("decision") or ""),
                    reviewer_note=payload.get("reviewer_note"),
                    edited_content=payload.get("edited_content"),
                )
            else:
                response_payload = await _process_turn(
                    session=session,
                    conversation_id=normalized_id,
                    user=user,
                    user_message=user_message,
                )

            await websocket.send_json(response_payload)

    except WebSocketDisconnect:
        return
