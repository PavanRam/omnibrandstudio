"""review_service pure-helper tests.

The DB-backed functions (persist_draft_batch / send_campaign_to_review / apply_decision / resume_campaign)
require Postgres + a LangGraph checkpointer and are exercised via the smoke test
and manual E2E verification; these cover the pure helpers in isolation.
"""
from services.review_service import _as_uuid_or_none, _format_rejection_message, _to_psycopg_dsn


def test_as_uuid_or_none_coerces_non_uuid_actor_to_none():
    # API-key auth uses the sentinel "api_key" — must become NULL, not crash the
    # UUID column (regression for the reviewed_by / audit actor_id DataError).
    assert _as_uuid_or_none("api_key") is None
    assert _as_uuid_or_none("") is None
    assert _as_uuid_or_none(None) is None


def test_as_uuid_or_none_passes_through_valid_uuid():
    uid = "019f808d-c528-7fb5-973c-2446c91f550e"
    assert _as_uuid_or_none(uid) == uid


def test_to_psycopg_dsn_strips_async_driver():
    dsn = _to_psycopg_dsn("postgresql+asyncpg://u:p@host:5432/db")
    assert dsn == "postgresql://u:p@host:5432/db"


def test_to_psycopg_dsn_escapes_bare_percent_in_password():
    dsn = _to_psycopg_dsn("postgresql+asyncpg://u:p%ss@host:5432/db")
    assert "%25" in dsn and "@host:5432/db" in dsn


def _rejected_row(**overrides):
    base = {"channel": "email", "locale": "en-US", "reviewer_note": "too salesy, tone it down"}
    base.update(overrides)
    return base


def test_format_rejection_message_lists_each_variant_with_its_own_comment():
    # 2026-07-27, item 6: reviewers can leave different comments per variant —
    # the creator-facing message must not collapse them into one generic
    # reason, each rejected item needs its own line with its own note.
    rows = [
        _rejected_row(channel="email", locale="en-US", reviewer_note="too salesy, tone down the CTA"),
        _rejected_row(channel="sms", locale="en-US", reviewer_note="over character limit, trim it"),
    ]
    message = _format_rejection_message(rows)

    assert "2 variants rejected" in message
    assert "email · en-US" in message
    assert "too salesy, tone down the CTA" in message
    assert "sms · en-US" in message
    assert "over character limit, trim it" in message


def test_format_rejection_message_singular_for_one_variant():
    message = _format_rejection_message([_rejected_row()])
    assert "1 variant rejected" in message
    assert "1 variants" not in message


def test_format_rejection_message_falls_back_when_no_note_left():
    message = _format_rejection_message([_rejected_row(reviewer_note=None)])
    assert "no comment left" in message
