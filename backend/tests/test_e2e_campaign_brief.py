"""E2E evaluation — multi-turn campaign-brief collection flow.

Drives _process_turn() directly with a scripted understanding_engine mock so
no real LLM calls are made.  Each test scenario covers one distinct invariant:

  SCENARIO A — incremental-natural  : objective arrives as prose (not JSON),
                fields are supplied one group per turn, green-light statuses
                accumulate correctly, confirm gate fires when brief is complete,
                campaign is only enqueued after explicit user confirmation.

  SCENARIO B — brief drops on welcome : user pastes full context in turn 1,
                engine extracts everything in one shot, confirm gate fires
                immediately, campaign enqueues on "yes".

  SCENARIO C — correction flow        : user corrects a previously captured
                field; brief re-enters incomplete state if correction removes
                a required field.

  SCENARIO D — premature-run blocked  : user says "run campaign" before brief
                is complete — must NOT enqueue, must continue collecting.

  SCENARIO E — awaiting + edited back : session is awaiting_confirmation, user
                provides a new value that changes the brief to incomplete;
                status must revert to collecting.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.deps import UserContext
from api.routers import conversations
from pipeline.conversation_models import (
    ConversationSession,
    ExtractionMeta,
    IntentClassification,
    PartialBrief,
    UnderstandingResult,
)

# ── shared fixtures ────────────────────────────────────────────────────────────

CONV_ID = "019e0000-0000-7000-8000-000000000001"
ORG_ID = "00000000-0000-0000-0000-000000000001"
BRAND_ID = "00000000-0000-0000-0000-000000000002"
CAMPAIGN_ID = "019e0000-0000-7000-8000-aabbccddeeff"

USER = UserContext(
    user_id="00000000-0000-0000-0000-000000000099",
    org_id=ORG_ID,
    brand_ids=[BRAND_ID],
    auth_method="api_key",
)

COMPLETE_BRIEF = PartialBrief(
    objective="Launch the Q3 SMB upsell push",
    target_audience="SMB decision-makers in APAC",
    channels=["linkedin", "email"],
    locales=["en-US", "en-AU"],
    audience_segments=["smb", "enterprise"],
    token_budget=4000,
)


def _make_session(
    status: str = "collecting",
    brief: PartialBrief | None = None,
    active_campaign_id: str | None = None,
) -> ConversationSession:
    return ConversationSession(
        id=CONV_ID,
        org_id=ORG_ID,
        brand_id=BRAND_ID,
        status=status,
        partial_brief=brief or PartialBrief(),
        active_campaign_id=active_campaign_id,
    )


def _understanding(
    brief: PartialBrief,
    intent: str = "collect_brief",
    confidence: float = 0.92,
    field_confidence: dict[str, float] | None = None,
) -> UnderstandingResult:
    return UnderstandingResult(
        intent=IntentClassification(
            primary=intent,  # type: ignore[arg-type]
            secondary=[],
            confidence=confidence,
        ),
        brief=brief,
        extraction_meta=ExtractionMeta(
            field_confidence=field_confidence or {},
            source="llm",
        ),
    )


def _patch_mocks(
    monkeypatch: pytest.MonkeyPatch,
    session: ConversationSession,
    understanding_side_effect: list[UnderstandingResult],
    enqueue_return: str = CAMPAIGN_ID,
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    """Patch all external I/O; return (understand_mock, enqueue_mock, set_status_mock)."""
    history_store: list[dict[str, str]] = []

    async def _add_message(conv_id: str, role: str, content: str, **_kw: Any) -> None:
        history_store.append({"role": role, "content": content})

    async def _load_messages(conv_id: str) -> list[dict[str, str]]:
        return list(history_store)

    async def _update_partial_brief(conv_id: str, brief: PartialBrief) -> None:
        session.partial_brief = brief  # mutate so next turn sees latest brief

    async def _set_status(conv_id: str, status: str) -> None:
        session.status = status  # mutate so next turn sees latest status

    monkeypatch.setattr(conversations.session_manager, "add_message", _add_message)
    monkeypatch.setattr(conversations.session_manager, "load_messages", _load_messages)
    monkeypatch.setattr(conversations.session_manager, "update_partial_brief", _update_partial_brief)
    monkeypatch.setattr(conversations.session_manager, "attach_campaign", AsyncMock())
    set_status_mock = AsyncMock(side_effect=_set_status)
    monkeypatch.setattr(conversations.session_manager, "set_status", set_status_mock)

    understand_mock = AsyncMock(side_effect=understanding_side_effect)
    monkeypatch.setattr(conversations.understanding_engine, "understand", understand_mock)

    enqueue_mock = AsyncMock(return_value=enqueue_return)
    monkeypatch.setattr(conversations, "_enqueue_campaign", enqueue_mock)

    # DB-backed, mocked per this repo's convention (see test_review_service.py
    # docstring) — no similar campaign for these e2e brief-flow tests.
    monkeypatch.setattr(conversations, "find_similar_campaign", AsyncMock(return_value=None))

    monkeypatch.setattr(
        conversations.conversation_responder,
        "respond",
        AsyncMock(return_value="[test-stub]"),
    )

    return understand_mock, enqueue_mock, set_status_mock


# ── helper to run a turn ──────────────────────────────────────────────────────

async def _turn(session: ConversationSession, message: str) -> dict[str, Any]:
    return await conversations._process_turn(
        session=session,
        conversation_id=CONV_ID,
        user=USER,
        user_message=message,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO A — Incremental-natural multi-turn collection
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_incremental_collection_and_confirmation_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Turn 1: objective only (prose) → captured, brief incomplete, no enqueue.
    Turn 2: channels + locales → captured, brief still incomplete, no enqueue.
    Turn 3: audience_segments + token_budget → brief NOW complete → confirm gate
            fires → status → awaiting_confirmation, NO enqueue yet.
    Turn 4: user says "yes" → campaign enqueues exactly once.
    """
    session = _make_session()
    monkeypatch.setattr(conversations.settings, "ENABLE_CONVERSATION_PLANNER", True)

    brief_after_t1 = PartialBrief(objective="Launch the Q3 SMB upsell push")
    brief_after_t2 = PartialBrief(
        objective="Launch the Q3 SMB upsell push",
        channels=["linkedin", "email"],
        locales=["en-US", "en-AU"],
    )
    brief_after_t3 = deepcopy(COMPLETE_BRIEF)

    understand_side_effects = [
        _understanding(brief_after_t1, field_confidence={"objective": 0.9}),
        _understanding(brief_after_t2),
        _understanding(brief_after_t3),
        _understanding(brief_after_t3, intent="submit_campaign", confidence=0.99),
    ]

    _, enqueue_mock, set_status_mock = _patch_mocks(
        monkeypatch, session, understand_side_effects
    )

    # ── Turn 1 ──────────────────────────────────────────────────────────────
    r1 = await _turn(session, "We want to upsell SMBs in Q3 across APAC.")

    assert r1["brief_complete"] is False, "Turn 1 brief must be incomplete"
    assert r1["campaign_id"] is None, "No campaign on incomplete brief"
    assert r1["awaiting_confirmation"] is False
    enqueue_mock.assert_not_awaited()

    # objective was captured → brief_updates must include it
    assert "the campaign objective" in r1["brief_updates"]

    # green-light field states: objective captured, rest missing
    fs = {s["field"]: s for s in r1["brief_field_states"]}
    assert fs["objective"]["status"] == "captured"
    assert fs["channels"]["status"] == "missing"

    # ── Turn 2 ──────────────────────────────────────────────────────────────
    r2 = await _turn(
        session,
        "Channels: LinkedIn and email; locales en-US and en-AU.",
    )

    assert r2["brief_complete"] is False
    assert r2["campaign_id"] is None
    assert r2["awaiting_confirmation"] is False
    enqueue_mock.assert_not_awaited()
    assert "the channels" in r2["brief_updates"]

    fs2 = {s["field"]: s for s in r2["brief_field_states"]}
    assert fs2["channels"]["status"] == "captured"
    assert fs2["audience_segments"]["status"] == "missing"

    # ── Turn 3 — brief completes → confirm gate ──────────────────────────────
    r3 = await _turn(
        session,
        "Audience segments are SMB and enterprise; budget is 4000 tokens.",
    )

    assert r3["brief_complete"] is True, "Brief must be complete after turn 3"
    assert r3["campaign_id"] is None, "Must NOT enqueue before confirmation"
    assert r3["awaiting_confirmation"] is True, "Confirm gate must fire"
    enqueue_mock.assert_not_awaited()

    # status must have been set to awaiting_confirmation
    set_status_mock.assert_awaited_with(CONV_ID, "awaiting_confirmation")

    # ── Turn 4 — user confirms ────────────────────────────────────────────────
    r4 = await _turn(session, "yes")

    assert r4["campaign_id"] == CAMPAIGN_ID, "Campaign must enqueue on confirmation"
    assert r4["brief_complete"] is True
    enqueue_mock.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO B — Full brief in one turn, then confirm
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_single_turn_full_brief_then_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Turn 1: user provides all fields at once → confirm gate fires immediately.
    Turn 2: "looks good, go ahead" → campaign enqueues.
    """
    session = _make_session()
    full = deepcopy(COMPLETE_BRIEF)

    _, enqueue_mock, set_status_mock = _patch_mocks(
        monkeypatch,
        session,
        [
            _understanding(full, field_confidence={f: 0.95 for f in full.model_fields}),
            _understanding(full, intent="submit_campaign"),
        ],
    )

    r1 = await _turn(session, "Here's everything: objective=Launch Q3 SMB ...")
    assert r1["brief_complete"] is True
    assert r1["campaign_id"] is None
    assert r1["awaiting_confirmation"] is True
    enqueue_mock.assert_not_awaited()
    set_status_mock.assert_awaited_with(CONV_ID, "awaiting_confirmation")

    r2 = await _turn(session, "looks good, go ahead")
    assert r2["campaign_id"] == CAMPAIGN_ID
    enqueue_mock.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO C — Field correction
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_field_correction_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Session starts with a complete brief; user corrects the objective (replaces
    it with a new value).  The brief stays complete, brief_changes contains the
    correction, correction_detected is True.
    """
    original = deepcopy(COMPLETE_BRIEF)
    corrected = deepcopy(COMPLETE_BRIEF)
    corrected.objective = "Revised: focus on renewals, not upsell"

    session = _make_session(brief=original)
    monkeypatch.setattr(conversations.settings, "ENABLE_CONVERSATION_PLANNER", True)

    _, enqueue_mock, _ = _patch_mocks(
        monkeypatch,
        session,
        [_understanding(corrected, intent="modify_brief")],
    )

    r = await _turn(session, "Actually, the objective should be about renewals.")

    assert r["brief_complete"] is True
    assert r["correction_detected"] is True

    obj_change = next(
        (c for c in r["brief_changes"] if c["field"] == "objective"), None
    )
    assert obj_change is not None, "objective change must be in brief_changes"
    assert obj_change["change_type"] == "replaced"
    assert obj_change["after"] == "Revised: focus on renewals, not upsell"


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO D — Premature "run campaign" blocked while brief is incomplete
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_premature_run_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    User says 'run campaign now' but objective is the only populated field.
    Must NOT enqueue; must NOT set awaiting_confirmation; continues collecting.
    """
    session = _make_session()
    partial = PartialBrief(objective="Test launch")

    _, enqueue_mock, set_status_mock = _patch_mocks(
        monkeypatch,
        session,
        [_understanding(partial, intent="submit_campaign")],
    )

    r = await _turn(session, "run campaign now")

    assert r["brief_complete"] is False
    assert r["campaign_id"] is None, "Must NOT enqueue on incomplete brief"
    assert r["awaiting_confirmation"] is False
    enqueue_mock.assert_not_awaited()
    # set_status should NOT have been called with awaiting_confirmation
    for call_args in set_status_mock.call_args_list:
        assert call_args.args[1] != "awaiting_confirmation", (
            "Must not transition to awaiting_confirmation with incomplete brief"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO E — Brief edited back to incomplete while awaiting confirmation
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_awaiting_reverts_to_collecting_on_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Session is already awaiting_confirmation with a complete brief.
    User then removes channels (sends an empty brief back).
    Status must revert to 'collecting'.
    """
    session = _make_session(status="awaiting_confirmation", brief=deepcopy(COMPLETE_BRIEF))
    # User's clarification removes channels
    without_channels = deepcopy(COMPLETE_BRIEF)
    without_channels.channels = []

    _, enqueue_mock, set_status_mock = _patch_mocks(
        monkeypatch,
        session,
        [_understanding(without_channels, intent="modify_brief")],
    )

    r = await _turn(session, "Actually, drop all channel selections for now.")

    assert r["brief_complete"] is False
    assert r["campaign_id"] is None
    enqueue_mock.assert_not_awaited()
    set_status_mock.assert_awaited_with(CONV_ID, "collecting")
