"""ReviewDecision validation: shared by the Postman/app ``/decide`` route and the
Airtable webhook route (``/airtable-decide``), so a rule added here applies to
both callers uniformly."""

import pytest
from pipeline.schemas import ReviewDecision
from pydantic import ValidationError


def test_rejected_without_reviewer_note_is_invalid():
    with pytest.raises(ValidationError, match="reviewer_note is required"):
        ReviewDecision(decision="rejected")


def test_rejected_with_whitespace_only_reviewer_note_is_invalid():
    with pytest.raises(ValidationError, match="reviewer_note is required"):
        ReviewDecision(decision="rejected", reviewer_note="   ")


def test_rejected_with_reviewer_note_is_valid():
    decision = ReviewDecision(decision="rejected", reviewer_note="too generic, redo")
    assert decision.reviewer_note == "too generic, redo"


def test_approved_without_reviewer_note_is_valid():
    decision = ReviewDecision(decision="approved")
    assert decision.reviewer_note is None


def test_edited_requires_edited_content():
    with pytest.raises(ValidationError, match="edited_content is required"):
        ReviewDecision(decision="edited")


def test_edited_content_only_allowed_for_edited_decision():
    with pytest.raises(ValidationError, match="edited_content may only be set"):
        ReviewDecision(decision="approved", edited_content="rewritten copy")


def test_reviewer_email_and_airtable_record_id_are_optional_passthrough_fields():
    decision = ReviewDecision(
        decision="approved",
        reviewer_email="reviewer@example.com",
        airtable_record_id="recABC123",
    )
    assert decision.reviewer_email == "reviewer@example.com"
    assert decision.airtable_record_id == "recABC123"
