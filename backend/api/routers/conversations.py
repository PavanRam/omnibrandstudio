from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from opentelemetry.propagate import inject
from pydantic import BaseModel
from sqlalchemy import text

from api.deps import UserContext, get_current_user
from api.middleware.auth import decode_access_token, is_jti_revoked
from core.config import settings
from core.ids import new_campaign_id, new_request_id
from core.redis import get_redis
from pipeline.agents.base import traced_llm_call
from pipeline.conversation_models import ConversationPlannerInput, ConversationSession, ExtractionMeta, IntentClassification, PartialBrief, SimilarCampaignMatch, UnderstandingResult
from pipeline.intake_validation import ROUGH_TOKENS_PER_TASK, estimate_task_count
from pipeline.locale_utils import SOURCE_LOCALE, SUPPORTED_LOCALES, is_locale_supported
from services.chat.brief_collector import brief_collector
from services.campaign.campaign_query import get_recent_campaigns
from services.campaign.similarity_service import find_similar_campaign
from services.chat.conversation_planner import conversation_planner
from services.chat.conversation_responder import conversation_responder
from services.chat.session_manager import session_manager
from services.chat.understanding_engine import understanding_engine
from services import review_service

log = structlog.get_logger()

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
    # Chat is tier-aware via JUDGE_TIER (the live Redis toggle is deferred).
    # free → Groq (*-free) aliases for $0 spend; paid → existing paid aliases.
    if (settings.JUDGE_TIER or "free").lower() == "paid":
        model_aliases = {
            "utility": "util-fast",
            "brief_collector": "brief-collector",
            "understanding": "understanding",
            "responder": "responder-chat",
        }
    else:
        model_aliases = {
            "utility": "util-fast-free",
            "brief_collector": "brief-collector-free",
            "understanding": "understanding-free",
            "responder": "responder-chat-free",
        }
    return {
        "campaign_id": session.active_campaign_id,
        "org_id": session.org_id,
        "brand_id": session.brand_id,
        "request_id": new_request_id(),
        "model_aliases": model_aliases,
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
    # token_budget removed from playback (2026-07-29): no longer collected from users.
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

    if planner_output and planner_output.reply_strategy == "witty_redirect":
        return (
            "Ha — that's a bit outside my wheelhouse; I'm more of a campaign person. "
            "Speaking of which, what are you looking to launch, and who do you want to reach?"
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


def _build_rejection_notice(rejected: dict[str, list[str]]) -> str:
    """Tell the user why a free-text mention of a channel/locale/segment
    didn't change anything, instead of silently dropping it — item 23d
    (2026-07-27). `rejected` comes from BriefCollector._merge()."""
    if not rejected:
        return ""

    parts: list[str] = []

    channels = rejected.get("channels") or []
    if channels:
        values = ", ".join(f"'{v}'" for v in channels)
        verb = "isn't" if len(channels) == 1 else "aren't"
        parts.append(f"{values} {verb} a supported channel for this brand")

    locales = rejected.get("locales") or []
    if locales:
        values = ", ".join(f"'{v}'" for v in locales)
        verb = "isn't" if len(locales) == 1 else "aren't"
        parts.append(f"{values} {verb} a supported locale")

    if rejected.get("audience_segments"):
        parts.append(
            "audience segments come from this brand's real segment data, not free text"
        )

    if not parts:
        return ""

    return "Heads up — " + "; ".join(parts) + ". Please select from the options below."


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


async def _campaign_status(campaign_id: str) -> str | None:
    from core.database import get_db

    async with get_db() as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM campaigns WHERE id = CAST(:cid AS UUID)"),
                {"cid": campaign_id},
            )
        ).mappings().first()
    return str(row["status"]) if row is not None else None


async def _rejected_task_ids(campaign_id: str) -> list[str]:
    from core.database import get_db

    # Edits/reruns INSERT a fresh content_variants row per re-run rather than
    # updating in place (same pattern as send_campaign_to_review's own query)
    # — DISTINCT ON picks only the newest row per task_id before filtering to
    # the ones still sitting at 'rejected'.
    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (task_id) task_id, status
                    FROM content_variants
                    WHERE campaign_id = CAST(:cid AS UUID)
                    ORDER BY task_id, created_at DESC
                    """
                ),
                {"cid": campaign_id},
            )
        ).mappings().all()
    return [str(r["task_id"]) for r in rows if r["status"] == "rejected"]


async def _handle_revision_reply(
    *,
    session: ConversationSession,
    conversation_id: str,
    user: UserContext,
    user_message: str,
) -> dict[str, Any]:
    """A campaign parked in 'needs_revision' (see review_service._park_for_revision)
    is waiting on the creator's next chat message as fix instructions for every
    currently-rejected variant — not a new brief turn. Regenerates only those
    variants (via the same single-task rerun_service path the "Modify prompt"
    feature already uses), then resubmits just the regenerated ones for review."""
    from services.campaign.rerun_service import rerun_service

    campaign_id = session.active_campaign_id
    assert campaign_id is not None

    task_ids = await _rejected_task_ids(campaign_id)
    for task_id in task_ids:
        await rerun_service.rerun_campaign(
            campaign_id=campaign_id,
            resume_from_node="content_generator",
            requested_by=user.user_id,
            trigger="reviewer_rejection_revision",
            user_edit=user_message,
            variant_task_id=task_id,
        )

    review_count = await review_service.send_campaign_to_review(campaign_id)

    plural = "variant" if len(task_ids) == 1 else "variants"
    assistant_message = (
        f"Regenerated {len(task_ids)} {plural} with your changes and sent "
        f"{'it' if review_count == 1 else 'them'} back to the reviewer."
        if task_ids
        else "Nothing was pending revision for this campaign anymore."
    )
    await session_manager.add_message(
        conversation_id,
        "assistant",
        assistant_message,
        intent_classified="revision_applied",
        campaign_id=campaign_id,
    )

    return {
        "conversation_id": conversation_id,
        "intent": "revision_applied",
        "brief": session.partial_brief.model_dump(),
        "brief_complete": session.partial_brief.is_complete(),
        "awaiting_confirmation": False,
        "campaign_id": campaign_id,
        "similar_campaign": None,
        "message": assistant_message,
        "brief_updates": [],
        "brief_changes": [],
        "conversation_stage": None,
        "planner_objective": None,
        "primary_objective": None,
        "secondary_objectives": [],
        "turn_type": None,
        "needs_clarification": False,
        "clarification_target": None,
        "brief_field_states": [],
        "suggested_prompts": [],
        "correction_detected": False,
        "pending_reviews": [],
    }


async def _process_turn(
    *,
    session: ConversationSession,
    conversation_id: str,
    user: UserContext,
    user_message: str,
    websocket: WebSocket | None = None,
) -> dict[str, Any]:
    async def _status(stage: str) -> None:
        # Real, in-flight pipeline stages — not a timer-driven guess. Lets the
        # frontend show a "doing X" indicator that always matches what's
        # actually running, since the socket is already open per conversation.
        # Logged explicitly (2026-07-27) — websocket.send_json itself produces
        # no server-side log line at all, so there was previously no way to
        # confirm from the server side whether this was ever actually firing.
        log.info("chat_status_pushed", conversation_id=conversation_id, stage=stage, has_socket=websocket is not None)
        if websocket is not None:
            await websocket.send_json({"type": "status", "stage": stage})

    await session_manager.add_message(conversation_id, "user", user_message)

    if session.active_campaign_id:
        campaign_status = await _campaign_status(session.active_campaign_id)
        if campaign_status == "needs_revision":
            return await _handle_revision_reply(
                session=session,
                conversation_id=conversation_id,
                user=user,
                user_message=user_message,
            )

    history = await session_manager.load_messages(conversation_id)
    context = _chat_state_context(session)
    await _status("understanding")
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
    await _status("checking_brief")

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
    campaign_copilot_message: str | None = None
    pending_reviews: list[dict[str, Any]] = []

    if intent in {"check_status", "explain_progress", "show_agent_output", "view_history"}:
        campaign_copilot_message = await _campaign_copilot_reply(
            conversation_id=conversation_id,
            session=session,
            intent=intent,
            user_message=user_message,
            state=context,
        )
    elif intent == "list_reviews" and session.active_campaign_id:
        pending_reviews = await _fetch_pending_reviews(session.active_campaign_id)
        campaign_copilot_message = _pending_reviews_message(pending_reviews)
    elif session.active_campaign_id:
        # Surface pending reviews automatically whenever the active campaign
        # is paused for review, regardless of what the user asked about.
        pending_reviews = await _fetch_pending_reviews(session.active_campaign_id)

    # ── Confirmation gate ────────────────────────────────────────────────
    # A complete brief is NOT enqueued immediately. The assistant first plays
    # the brief back and waits; the campaign runs only after the user confirms.
    brief_complete = brief.is_complete()
    was_awaiting = session.status == "awaiting_confirmation"
    explicit_run = ("run" in user_message.lower() and "campaign" in user_message.lower()) or intent == "submit_campaign"
    affirmative = _is_affirmative(user_message)

    should_run = False
    confirm_playback = False
    similar_campaign: SimilarCampaignMatch | None = None
    if brief_complete and not session.active_campaign_id and not campaign_copilot_message:
        if was_awaiting and (affirmative or explicit_run):
            should_run = True
        elif not was_awaiting:
            # Brief just became complete for the first time — check
            # similarity right here, before ever asking "shall I run this?",
            # so a match is visible the moment the brief is ready rather than
            # only after the user already said yes. Checking against the
            # SAME turn that renders the brief panel (not a later bare "yes"
            # message, which carries no brief content of its own) also keeps
            # the brief/brief_field_states in this response fully populated.
            await _status("checking_similar")
            similar_campaign = await find_similar_campaign(brand_id=session.brand_id, brief=brief)
            if similar_campaign is None:
                confirm_playback = True
        else:
            confirm_playback = True

    if should_run:
        campaign_id = await _enqueue_campaign(
            user=user,
            brand_id=session.brand_id,
            brief=brief,
            request_id=new_request_id(),
        )
        await session_manager.attach_campaign(conversation_id, campaign_id)
    elif confirm_playback:
        if not was_awaiting:
            await session_manager.set_status(conversation_id, "awaiting_confirmation")
    elif similar_campaign is not None:
        # Held for a decision (Verify / Proceed anyway) rather than enqueued
        # — still mark the session as "awaiting" so a later confirmation
        # (should the user type instead of using the card) resumes correctly.
        if not was_awaiting:
            await session_manager.set_status(conversation_id, "awaiting_confirmation")
    elif was_awaiting and not brief_complete:
        # User edited the brief back into an incomplete state; resume collecting.
        await session_manager.set_status(conversation_id, "collecting")

    await _status("drafting_reply")
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
        similar_campaign=similar_campaign,
    )
    rejection_notice = _build_rejection_notice(extraction_meta.rejected)
    if rejection_notice:
        assistant_message = f"{rejection_notice} {assistant_message}".strip()

    await session_manager.add_message(
        conversation_id,
        "assistant",
        assistant_message,
        intent_classified=intent,
        campaign_id=campaign_id,
        captured=brief_updates,
        changes=brief_changes,
    )

    return {
        "conversation_id": conversation_id,
        "intent": intent,
        "brief": brief.model_dump(),
        "brief_complete": brief.is_complete(),
        "awaiting_confirmation": confirm_playback,
        "campaign_id": campaign_id,
        "similar_campaign": similar_campaign.model_dump() if similar_campaign else None,
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
    }


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
        merged, _ = brief_collector._merge(previous_brief, {}, user_message)
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
    similar_campaign: SimilarCampaignMatch | None = None,
) -> str:
    if similar_campaign:
        return (
            "This looks similar to an existing campaign — check the card above before "
            "creating a new one."
        )

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
    state: dict[str, Any],
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
        return await _campaign_agent_output_reply(campaign_id, user_message, summary, trace, state)
    if intent == "view_history":
        return _campaign_history_reply(conversation_id, campaign_id, summary)
    return None


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


_KNOWN_AGENTS: tuple[str, ...] = (
    "content_generator",
    "personalization_agent",
    "translation_agent",
    "judge_claude",
    "judge_gpt4o",
    "judge_llama",
    "confidence_aggregator",
    "review_gate",
    "publishing_agent",
)

AGENT_TARGET_PROMPT = (
    "You are a narrow classifier for resolving which running-campaign pipeline agent(s) "
    "the user is referring to.\n\n"
    f"Known agents: {', '.join(_KNOWN_AGENTS)}\n\n"
    "Task: infer the intended agent names from the user's message.\n"
    'Reply with ONLY a valid JSON object in the form: {"agents": [...]}.\n\n'
    "Rules:\n"
    "- Return only agent names from the known agents list.\n"
    "- If the user names one or more specific agents, return exactly those known agent names.\n"
    "- Match loosely phrased references when the intent is clear, including singular/plural forms, "
    "common synonyms, role labels, and group references.\n"
    '- Example: "the judges" should map to all judge_* agents if that meaning is clear.\n'
    '- Example: "all of them", "both", "everything", or "show me all outputs" should return every known agent name.\n'
    "- If the user explicitly asks for a subset, return only that subset.\n"
    "- Do not include agents mentioned only as examples, comparisons, negations, or things the user says they do not want.\n"
    "- If the message is ambiguous between multiple agent sets, return the smallest set that is clearly supported.\n"
    "- If no usable signal exists, return an empty list.\n"
    "- Do not guess, explain, add prose, add markdown, or include any keys other than agents.\n"
    "- Preserve the canonical spelling of each agent name exactly as it appears in Known agents.\n"
)


async def _resolve_requested_agents(user_message: str, state: dict[str, Any]) -> list[str]:
    """LLM-resolved agent target for a `show_agent_output` turn — replaces the old
    pure-keyword `_extract_requested_agent`, which had no entry for "all"/"both"/
    "everything" and so repeated the same canned prompt forever once a user
    answered a clarifying question with anything but a literal agent name (see
    next_tasks.md item 8, 2026-07-26).

    Cheap fast path first: a literal agent-name match needs no LLM call at all.
    Only unresolved messages fall through to a `util-fast` classification call,
    kept deliberately tiny (one message, temperature 0) since this is a
    reply-composition detail, not a generation step.
    """
    direct = _extract_requested_agent(user_message)
    if direct:
        return [direct]

    try:
        content, _usage = await traced_llm_call(
            model=state.get("model_aliases", {}).get("utility", "util-fast"),
            messages=[
                {"role": "system", "content": _AGENT_TARGET_PROMPT},
                {"role": "user", "content": user_message},
            ],
            task="campaign_copilot_agent_resolution",
            state=state,
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(content)
        agents = parsed.get("agents") if isinstance(parsed, dict) else None
        if not isinstance(agents, list):
            return []
        return [a for a in agents if a in _KNOWN_AGENTS]
    except Exception:
        # Best-effort: degrade to "couldn't resolve" rather than breaking the turn.
        return []


async def _campaign_agent_output_reply(
    campaign_id: str,
    user_message: str,
    summary: dict[str, Any],
    trace: list[dict[str, Any]],
    state: dict[str, Any],
) -> str:
    requested_agents = await _resolve_requested_agents(user_message, state)
    if requested_agents:
        lines = []
        for agent_name in requested_agents:
            trace_line = _agent_trace_line(trace, agent_name)
            lines.append(
                f"{agent_name}: {trace_line}" if trace_line else f"{agent_name}: no output recorded yet"
            )
        joined = " | ".join(lines)
        return (
            f"Campaign {campaign_id} — {joined}. "
            f"Overall status is '{summary['status']}' with {summary['total_variants']} variants."
        )
    return (
        "Tell me which agent output you want (for example: content_generator, personalization_agent, or judge_claude — "
        "or say \"all of them\"), and I will summarize the latest campaign state around that step."
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
    for agent_name in _KNOWN_AGENTS:
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
        # token_budget no longer collected from users (2026-07-29): default to a safe
        # 200k so intake's >0 sanity check passes; actual usage tracked end-to-end.
        "token_budget": brief.token_budget or 200000,
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


@router.post("/conversations/{conversation_id}/run-anyway")
async def run_campaign_anyway(
    conversation_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Enqueues the session's current brief directly, bypassing intent
    classification and the similarity check entirely — the "Proceed anyway"
    action on a similar-campaign flag card. The check already ran once for
    this exact brief inside _process_turn; re-running it here would just
    repeat the same (free, local) embedding call for a decision the user
    already made."""
    session = await session_manager.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if session.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="conversation does not belong to org"
        )
    _assert_brand_access(user, session.brand_id)

    if session.active_campaign_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="conversation already has an active campaign",
        )
    if not session.partial_brief.is_complete():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="brief is not complete"
        )

    campaign_id = await _enqueue_campaign(
        user=user,
        brand_id=session.brand_id,
        brief=session.partial_brief,
        request_id=new_request_id(),
    )
    await session_manager.attach_campaign(conversation_id, campaign_id)
    # This bypasses _process_turn entirely (a button click, not a chat
    # message), which previously meant it left zero trace in the
    # conversation — no confirmation that anything happened at all, unlike
    # the normal "type run campaign" path which posts this exact message.
    # See next_tasks.md 2026-07-26 ("where is the approval or yes command,
    # you just started the queue").
    queued_message = (
        "Campaign queued successfully. "
        f"Campaign ID: {campaign_id}. You can subscribe to /campaigns/{campaign_id}/stream."
    )
    await session_manager.add_message(conversation_id, "assistant", queued_message)
    return {"campaign_id": campaign_id, "message": queued_message}


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Soft-archives a conversation (status='archived') so it drops out of
    the sidebar without deleting anything — user-requested cleanup option
    (2026-07-26), deliberately non-destructive."""
    session = await session_manager.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if session.org_id != user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="conversation does not belong to org"
        )
    _assert_brand_access(user, session.brand_id)

    await session_manager.set_status(conversation_id, "archived")
    return {"status": "archived"}


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


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Full message history for a conversation, oldest first — used to
    reconstruct the chat view when resuming an old conversation from the
    sidebar (the live WebSocket only ever carries *new* turns)."""
    from core.database import get_db

    normalized_id = _normalize_uuid(conversation_id, "conversation_id")
    session = await session_manager.get(normalized_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    _assert_brand_access(user, session.brand_id)

    async with get_db() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT role, content, campaign_id, created_at, captured, changes
                    FROM conversation_messages
                    WHERE conversation_id = CAST(:cid AS UUID)
                    ORDER BY created_at ASC
                    """
                ),
                {"cid": normalized_id},
            )
        ).mappings().all()

    # The similar-campaign flag is otherwise only ever delivered once, over
    # the live WebSocket message that triggered it — nothing persists it.
    # Since this app does full page navigations between routes (not a
    # client-side SPA) and conversation switches deliberately reset the
    # frontend's flag state, both would silently lose it even though the
    # underlying situation (an unresolved duplicate-looking brief) hasn't
    # changed. Recomputing it here — cheap, local embeddings, no LLM cost —
    # whenever a conversation is (re)loaded restores it reliably instead.
    similar_campaign: SimilarCampaignMatch | None = None
    if (
        session.status == "awaiting_confirmation"
        and not session.active_campaign_id
        and session.partial_brief.is_complete()
    ):
        similar_campaign = await find_similar_campaign(
            brand_id=session.brand_id, brief=session.partial_brief
        )

    return {
        "conversation_id": normalized_id,
        "messages": [
            {
                "role": r["role"],
                "content": r["content"],
                "campaign_id": str(r["campaign_id"]) if r["campaign_id"] else None,
                "created_at": r["created_at"],
                "captured": r["captured"] or [],
                "changes": r["changes"] or [],
            }
            for r in rows
        ],
        "similar_campaign": similar_campaign.model_dump() if similar_campaign else None,
    }


# ── Structured brief inputs (next_tasks.md item 23, 2026-07-27) ─────────────
# Pills/dropdown/tier-picker selections bypass understanding_engine/
# brief_collector's LLM extraction entirely — that's the actual design
# choice that closes the whole "locale as 'English', channel as 'SMS',
# audience-segment infinite loop" bug class this session kept hitting, not
# just a UI layer on top of the same fragile free-text parsing.

_LOCALE_LABELS = {
    "en-US": "English (US)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
}

_SETTABLE_BRIEF_FIELDS = {"channels", "locales", "audience_segments", "token_budget"}


@router.get("/locales/supported")
async def _brand_config(brand_id: str | None) -> dict:
    """Same brands.config lookup intake_agent uses for entitlement
    enforcement (pipeline/agents/intake.py::_load_brand_profile) — reused
    here so the pickers only ever offer what a brief would actually be
    allowed to use, not the full global set for brands that have configured
    a narrower allow-list (item 42, 2026-07-27). Fails open on any error —
    same reasoning as intake_agent's copy of this lookup."""
    if not brand_id:
        return {}
    from core.database import get_db

    try:
        async with get_db() as conn:
            result = await conn.execute(
                text("SELECT config FROM brands WHERE id = :brand_id"),
                {"brand_id": brand_id},
            )
            row = result.mappings().first()
            return dict(row["config"] or {}) if row and row["config"] else {}
    except Exception:  # noqa: BLE001
        return {}


@router.get("/locales/supported")
async def get_supported_locales(brand_id: str | None = None) -> dict:
    """Canonical locale pill options — the exact same source of truth
    translation_agent gates against (pipeline/locale_utils.py), so a pill
    selection can never produce a locale the pipeline doesn't actually
    support (unlike free-text extraction, which has repeatedly produced
    unsupported/malformed locale values this session). Narrowed further by
    the brand's own configured allow-list, if it has one (item 42)."""
    config = await _brand_config(brand_id)
    allowed = config.get("locales")
    codes = [SOURCE_LOCALE] + sorted(set(allowed) if allowed else SUPPORTED_LOCALES)
    return {"locales": [{"code": code, "label": _LOCALE_LABELS.get(code, code)} for code in codes]}


@router.get("/channels/supported")
async def get_supported_channels(brand_id: str | None = None) -> dict:
    """Canonical channel pill options — the exact same source of truth
    content_generator actually has a prompt template for
    (pipeline/agents/prompts/channel_prompts.py's DEFAULT_CHANNEL_CONSTRAINTS).
    Added 2026-07-27 after a live campaign requested "RCS" as a channel via
    free-text chat and failed mid-pipeline with "No prompt template seeded
    for channel 'rcs'" — RCS was never in DEFAULT_CHANNEL_CONSTRAINTS at
    all, so this picker can never offer it (or any other channel that would
    hard-fail generation), closing that failure mode at the source instead
    of catching it after wasted generation cost. Narrowed further by the
    brand's own configured allow-list, if it has one (item 42)."""
    from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS

    config = await _brand_config(brand_id)
    allowed = config.get("channels")
    channels = set(allowed) if allowed else set(DEFAULT_CHANNEL_CONSTRAINTS.keys())
    return {"channels": sorted(channels & set(DEFAULT_CHANNEL_CONSTRAINTS.keys()))}


class EstimateBudgetRequest(BaseModel):
    channels: list[str] = []
    locales: list[str] = []
    audience_segments: list[str] = []


@router.post("/conversations/{conversation_id}/estimate-budget")
async def estimate_budget(
    conversation_id: str,
    body: EstimateBudgetRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Budget-tier suggestions computed live from the existing
    check_budget/ROUGH_TOKENS_PER_TASK estimator (pipeline/intake_validation.py)
    — not fixed round numbers — given whatever channels/locales/segments are
    already selected (falls back to the conversation's current partial
    brief for anything not passed explicitly)."""
    normalized_id = _normalize_uuid(conversation_id, "conversation_id")
    session = await session_manager.get(normalized_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    _assert_brand_access(user, session.brand_id)

    channels = body.channels or session.partial_brief.channels
    locales = body.locales or session.partial_brief.locales
    segments = body.audience_segments or session.partial_brief.audience_segments
    task_count = estimate_task_count(channels, locales, segments) if (channels and locales and segments) else 1
    base_tokens = task_count * ROUGH_TOKENS_PER_TASK

    # Same "credit load" pattern as a $10/$15/$25/$50 top-up picker — tiers
    # scale off the real estimate rather than being arbitrary fixed amounts,
    # rounded to a clean multiple of 500 for readability.
    def _round_clean(n: float) -> int:
        return max(500, round(n / 500) * 500)

    tiers = [
        {"tokens": _round_clean(base_tokens * multiplier), "multiplier": multiplier}
        for multiplier in (1, 1.5, 2.5, 5)
    ]
    return {"task_count": task_count, "estimated_tokens": base_tokens, "tiers": tiers}


class SetBriefFieldRequest(BaseModel):
    field: str
    value: Any


@router.post("/conversations/{conversation_id}/set-brief-field")
async def set_brief_field(
    conversation_id: str,
    body: SetBriefFieldRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> dict:
    """Directly patch one brief field from a structured UI selection —
    deliberately bypasses understanding_engine/brief_collector's LLM
    extraction entirely for these three fields, per the item 23 design
    decision (2026-07-27): a pill/dropdown/tier selection is already
    unambiguous, so re-formatting it into a chat message and re-parsing it
    with an LLM would just reintroduce the same extraction fragility this
    endpoint exists to remove."""
    if body.field not in _SETTABLE_BRIEF_FIELDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"field must be one of {sorted(_SETTABLE_BRIEF_FIELDS)}",
        )
    normalized_id = _normalize_uuid(conversation_id, "conversation_id")
    session = await session_manager.get(normalized_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    _assert_brand_access(user, session.brand_id)

    brief = session.partial_brief.model_copy()
    if body.field == "channels":
        from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS

        if not isinstance(body.value, list) or not all(isinstance(v, str) for v in body.value):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "channels must be a list of strings")
        unsupported = [ch for ch in body.value if ch not in DEFAULT_CHANNEL_CONSTRAINTS]
        if unsupported:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unsupported channel(s): {unsupported}"
            )
        brief.channels = body.value
        summary = ", ".join(body.value)
    elif body.field == "locales":
        if not isinstance(body.value, list) or not all(isinstance(v, str) for v in body.value):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "locales must be a list of strings")
        unsupported = [loc for loc in body.value if not is_locale_supported(loc)]
        if unsupported:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unsupported locale(s): {unsupported}"
            )
        brief.locales = body.value
        summary = ", ".join(body.value)
    elif body.field == "audience_segments":
        if not isinstance(body.value, list) or not all(isinstance(v, str) for v in body.value):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "audience_segments must be a list of strings"
            )
        brief.audience_segments = body.value
        summary = ", ".join(body.value)
    else:  # token_budget
        if not isinstance(body.value, int) or body.value <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "token_budget must be a positive integer")
        brief.token_budget = body.value
        summary = f"{body.value:,} tokens"

    await session_manager.update_partial_brief(normalized_id, brief)

    field_label = body.field.replace("_", " ")
    # Persist the pick as its own user-turn message too, not just the
    # assistant's ack — otherwise a reload/conversation-switch re-fetches
    # history from GET /conversations/{id}/messages and the selection bubble
    # the frontend showed live (built purely client-side) is gone, since it
    # was never actually saved server-side (2026-07-27 persistence bug).
    user_message = f"{field_label.capitalize()}: {summary}"
    await session_manager.add_message(normalized_id, "user", user_message)
    ack_message = f"Got it — {field_label} set to {summary}."
    await session_manager.add_message(normalized_id, "assistant", ack_message)

    is_complete = brief.is_complete()
    if is_complete:
        await session_manager.set_status(normalized_id, "awaiting_confirmation")

    return {
        "brief": brief.model_dump(),
        "missing_slots": brief.missing_slots(),
        "is_complete": is_complete,
        "awaiting_confirmation": is_complete,
        "message": ack_message,
    }


@router.get("/me/recent-campaigns")
async def recent_campaigns(
    user: Annotated[UserContext, Depends(get_current_user)],
    include_archived: bool = False,
) -> dict[str, Any]:
    # Admins see every campaign in their brand scope (not just their own) so
    # they can actually find something to archive per the 2026-07-26
    # permission split; regular users keep the existing "my campaigns" view
    # and never see archived ones regardless of what they pass.
    is_admin = "admin" in user.roles
    campaigns = await get_recent_campaigns(
        org_id=user.org_id,
        brand_ids=user.brand_ids,
        created_by=None if is_admin else _optional_uuid(user.user_id),
        include_archived=include_archived and is_admin,
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
                    websocket=websocket,
                )

            await websocket.send_json(response_payload)

    except WebSocketDisconnect:
        return
