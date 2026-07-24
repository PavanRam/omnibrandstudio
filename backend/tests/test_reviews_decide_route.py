"""POST /reviews/{id}/decide — the human/Postman decision route.

Regression coverage for the actor-impersonation finding: this route must never
forward a caller-supplied ``reviewer_email`` into ``apply_decision`` — only the
authenticated caller's own identity (``user.user_id``) may become the audit
actor here. Attribution-by-email is only available via the separately-scoped
``/airtable-decide`` route (see test_reviews_airtable_decide.py), and even there
only after resolving to a real user.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from api.deps import UserContext
from api.routers import reviews
from fastapi import HTTPException, Response
from pipeline.schemas import ReviewDecision


def _user() -> UserContext:
    return UserContext(
        user_id="019f76e9-c299-7756-a483-761aa106ba11",
        org_id="00000000-0000-0000-0000-000000000001",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
        auth_method="api_key",
    )


async def test_reviewer_email_in_body_is_never_forwarded_to_apply_decision(monkeypatch):
    apply_mock = AsyncMock(
        return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": False}
    )
    monkeypatch.setattr(reviews.review_service, "apply_decision", apply_mock)

    body = ReviewDecision(decision="approved", reviewer_email="someone-else@example.com")
    await reviews.decide_review("rr-1", body, Response(), _user())

    apply_mock.assert_awaited_once_with(
        "rr-1",
        "approved",
        None,
        None,
        actor_id="019f76e9-c299-7756-a483-761aa106ba11",
        brand_ids=["00000000-0000-0000-0000-000000000002"],
    )


async def test_approve_all_decided_resumes_campaign(monkeypatch):
    apply_mock = AsyncMock(
        return_value={"campaign_id": "camp-1", "task_id": "t1", "all_decided": True}
    )
    resume_mock = AsyncMock(return_value="published")
    monkeypatch.setattr(reviews.review_service, "apply_decision", apply_mock)
    monkeypatch.setattr(reviews.review_service, "resume_campaign", resume_mock)

    body = ReviewDecision(decision="approved")
    result = await reviews.decide_review("rr-2", body, Response(), _user())

    assert result["status"] == "resumed"
    assert result["campaign_status"] == "published"
    resume_mock.assert_awaited_once_with("camp-1")


async def test_already_decided_maps_to_409(monkeypatch):
    monkeypatch.setattr(
        reviews.review_service,
        "apply_decision",
        AsyncMock(side_effect=ValueError("review already decided (status=approved)")),
    )

    body = ReviewDecision(decision="approved")
    with pytest.raises(HTTPException) as exc_info:
        await reviews.decide_review("rr-3", body, Response(), _user())

    assert exc_info.value.status_code == 409
