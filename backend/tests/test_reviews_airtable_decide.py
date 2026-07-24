"""POST /reviews/{id}/airtable-decide — the Airtable Automation webhook target.

Calls the route function directly (same style as test_chat_first_routes.py) rather
than spinning up a TestClient: deps are injected as plain arguments, and
``review_service``/``airtable_service`` are patched on the ``reviews`` module.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from api.deps import UserContext
from api.routers import reviews
from fastapi import HTTPException

_SERVICE_ACTOR_ID = "019f76e9-c299-7756-a483-761aa106ba11"


def _user() -> UserContext:
    return UserContext(
        user_id=_SERVICE_ACTOR_ID,
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )


def _mock_services(
    monkeypatch, *, apply_decision=None, resume_campaign=None, resolve_reviewer_email=None
):
    apply_mock = apply_decision or AsyncMock()
    resume_mock = resume_campaign or AsyncMock()
    mark_mock = AsyncMock()
    resolve_mock = resolve_reviewer_email or AsyncMock(return_value=None)
    monkeypatch.setattr(reviews.review_service, "apply_decision", apply_mock)
    monkeypatch.setattr(reviews.review_service, "resume_campaign", resume_mock)
    monkeypatch.setattr(reviews.review_service, "resolve_reviewer_email", resolve_mock)
    monkeypatch.setattr(reviews.airtable_service, "mark_synced", mark_mock)
    return apply_mock, resume_mock, mark_mock, resolve_mock


async def test_reject_without_note_returns_422_and_marks_error(monkeypatch):
    apply_mock, _, mark_mock, _resolve = _mock_services(monkeypatch)

    body = {"airtable_record_id": "rec1", "decision": "Rejected", "reviewer_note": ""}
    with pytest.raises(HTTPException) as exc_info:
        await reviews.airtable_decide("rr-1", body, _user())

    assert exc_info.value.status_code == 422
    apply_mock.assert_not_awaited()
    mark_mock.assert_awaited_once()
    args, kwargs = mark_mock.call_args
    assert args == ("rec1",)
    assert kwargs["status"] == "Error"
    assert "reviewer_note is required" in kwargs["error"]


async def test_edited_decision_is_rejected_before_apply_decision(monkeypatch):
    apply_mock, _, mark_mock, _resolve = _mock_services(monkeypatch)

    body = {"airtable_record_id": "rec2", "decision": "Edited", "reviewer_note": "rewrite it"}
    with pytest.raises(HTTPException) as exc_info:
        await reviews.airtable_decide("rr-2", body, _user())

    assert exc_info.value.status_code == 422
    assert "Editing must be done via the app" in str(exc_info.value.detail)
    apply_mock.assert_not_awaited()
    mark_mock.assert_awaited_once_with(
        "rec2",
        status="Error",
        error="Editing must be done via the app; use Approved or Rejected here.",
    )


async def test_approve_all_decided_resumes_campaign(monkeypatch):
    apply_mock, resume_mock, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": True}
        ),
        resume_campaign=AsyncMock(return_value="published"),
    )

    body = {"airtable_record_id": "rec3", "decision": "Approved"}
    result = await reviews.airtable_decide("rr-3", body, _user())

    assert result == {
        "review_request_id": "rr-3",
        "decision": "approved",
        "status": "resumed",
        "campaign_status": "published",
    }
    apply_args, apply_kwargs = apply_mock.call_args
    assert apply_args == ("rr-3", "approved", None, None)
    # No reviewer_email supplied — the calling service principal is the actor,
    # and apply_decision no longer accepts a reviewer_email override at all.
    assert apply_kwargs == {
        "actor_id": _SERVICE_ACTOR_ID,
        "brand_ids": ["00000000-0000-0000-0000-000000000002"],
    }
    resume_mock.assert_awaited_once_with("camp-1")
    mark_mock.assert_awaited_once_with("rec3", status="Synced")


async def test_reviewer_email_resolves_to_actor_override(monkeypatch):
    reviewer_user_id = "019f76e9-c299-7756-a483-761aa106baaa"
    apply_mock, _resume, mark_mock, resolve_mock = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": False}
        ),
        resolve_reviewer_email=AsyncMock(return_value=reviewer_user_id),
    )

    body = {
        "airtable_record_id": "rec3b",
        "decision": "Approved",
        "reviewer_email": "reviewer@example.com",
    }
    await reviews.airtable_decide("rr-3b", body, _user())

    resolve_mock.assert_awaited_once_with("reviewer@example.com")
    _, apply_kwargs = apply_mock.call_args
    # The decision is attributed to the resolved reviewer, not the service key.
    assert apply_kwargs["actor_id"] == reviewer_user_id
    mark_mock.assert_awaited_once_with("rec3b", status="Synced")


async def test_unresolvable_reviewer_email_is_rejected_not_defaulted(monkeypatch):
    apply_mock, _resume, mark_mock, resolve_mock = _mock_services(
        monkeypatch,
        resolve_reviewer_email=AsyncMock(return_value=None),
    )

    body = {
        "airtable_record_id": "rec3c",
        "decision": "Approved",
        "reviewer_email": "not-a-real-user@example.com",
    }
    with pytest.raises(HTTPException) as exc_info:
        await reviews.airtable_decide("rr-3c", body, _user())

    assert exc_info.value.status_code == 422
    assert "does not match any known user" in str(exc_info.value.detail)
    # Must NOT silently fall back and apply the decision under the service actor —
    # an unresolvable reviewer_email is rejected outright (regression guard for the
    # actor-impersonation/audit-spoofing finding).
    apply_mock.assert_not_awaited()
    mark_mock.assert_awaited_once_with(
        "rec3c",
        status="Error",
        error="reviewer_email 'not-a-real-user@example.com' does not match any known user",
    )


async def test_approve_other_reviews_still_pending_does_not_resume(monkeypatch):
    apply_mock, resume_mock, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": False}
        ),
    )

    body = {"airtable_record_id": "rec4", "decision": "approved"}
    result = await reviews.airtable_decide("rr-4", body, _user())

    assert result["status"] == "recorded"
    assert result["campaign_status"] == "awaiting_review"
    resume_mock.assert_not_awaited()
    mark_mock.assert_awaited_once_with("rec4", status="Synced")


async def test_already_decided_is_idempotent_success(monkeypatch):
    apply_mock, resume_mock, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            side_effect=ValueError("review already decided (status=approved)")
        ),
    )

    body = {"airtable_record_id": "rec5", "decision": "rejected", "reviewer_note": "no good"}
    result = await reviews.airtable_decide("rr-5", body, _user())

    assert result == {
        "review_request_id": "rr-5",
        "decision": "rejected",
        "status": "already_decided",
    }
    resume_mock.assert_not_awaited()
    mark_mock.assert_awaited_once_with("rec5", status="Synced")


async def test_lookup_error_maps_to_404_and_marks_error(monkeypatch):
    apply_mock, _, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(side_effect=LookupError("review request not found")),
    )

    body = {"airtable_record_id": "rec6", "decision": "approved"}
    with pytest.raises(HTTPException) as exc_info:
        await reviews.airtable_decide("rr-6", body, _user())

    assert exc_info.value.status_code == 404
    mark_mock.assert_awaited_once_with("rec6", status="Error", error="review request not found")


async def test_permission_error_maps_to_403_and_marks_error(monkeypatch):
    apply_mock, _, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(side_effect=PermissionError("review request outside brand scope")),
    )

    body = {"airtable_record_id": "rec7", "decision": "approved"}
    with pytest.raises(HTTPException) as exc_info:
        await reviews.airtable_decide("rr-7", body, _user())

    assert exc_info.value.status_code == 403
    mark_mock.assert_awaited_once_with(
        "rec7", status="Error", error="review request outside brand scope"
    )


async def test_missing_record_id_still_applies_decision_but_skips_write_back(monkeypatch):
    apply_mock, _, mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": False}
        ),
    )

    body = {"decision": "approved"}  # no airtable_record_id
    result = await reviews.airtable_decide("rr-8", body, _user())

    assert result["status"] == "recorded"
    apply_mock.assert_awaited_once()
    mark_mock.assert_not_awaited()


async def test_decision_value_is_case_and_whitespace_normalized(monkeypatch):
    apply_mock, _, _mark_mock, _resolve = _mock_services(
        monkeypatch,
        apply_decision=AsyncMock(
            return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": False}
        ),
    )

    body = {"decision": "  REJECTED  ", "reviewer_note": "not on brand"}
    await reviews.airtable_decide("rr-9", body, _user())

    apply_args, _ = apply_mock.call_args
    assert apply_args[1] == "rejected"
