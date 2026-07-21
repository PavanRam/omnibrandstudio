"""T11 — review_service pure-helper tests (regression for E2E bugs).

The DB-backed functions (persist_review_batch / apply_decision / resume_campaign)
are exercised end-to-end against Postgres; these cover the pure helpers that
caused failures during that run.
"""
from services.review_service import _as_uuid_or_none, _to_psycopg_dsn


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
