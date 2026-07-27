"""similarity_service pure-helper tests.

find_similar_campaign() itself is DB-backed (Postgres) — following this
repo's existing convention (see test_review_service.py), DB-backed functions
are exercised via the smoke test / manual E2E verification rather than
mocked here. These cover the pure scoring helpers in isolation.
"""
from services.campaign.similarity_service import _brief_text, _cosine, _jaccard


def test_jaccard_identical_sets_is_one():
    assert _jaccard(["email", "sms"], ["sms", "email"]) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert _jaccard(["email"], ["sms"]) == 0.0


def test_jaccard_partial_overlap():
    assert _jaccard(["email", "sms"], ["email"]) == 0.5


def test_jaccard_both_empty_is_one():
    # No channels specified on either side isn't a mismatch signal.
    assert _jaccard([], []) == 1.0


def test_jaccard_one_empty_is_zero():
    assert _jaccard(["email"], []) == 0.0


def test_jaccard_is_case_insensitive():
    assert _jaccard(["Email"], ["email"]) == 1.0


def test_cosine_identical_vectors_is_one():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_orthogonal_vectors_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_zero_vector_does_not_divide_by_zero():
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_brief_text_joins_and_strips():
    assert _brief_text(" Boost sales ", " students ") == "Boost sales students"


def test_brief_text_handles_empty_audience():
    assert _brief_text("Boost sales", "") == "Boost sales"
