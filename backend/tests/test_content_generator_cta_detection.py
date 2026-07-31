"""_has_element()/_check_constraints() coverage for premium/luxury CTA phrasing.

Root cause (2026-07-31, store-spenders end-of-season campaign): content_generator
repeatedly marked email/linkedin variants "failed" after 3 retries with
"missing required element: cta" (and "subject_line" for email) whenever the
brief requested a premium tone with "Avoid: discount language, hard-sell
urgency, informal tone". The CTA detector in content_generator.py only
recognized hard-sell-style verbs/markers (click, shop now, sign up, ...);
softer luxury-register phrasing a model naturally reaches for under that tone
constraint (priority access, private appointment, RSVP, confirm/secure/hold
your ..., await, indulge) matched none of them, and a title-style subject
line with no literal "Subject:" prefix wasn't recognized either. Fixed by
widening _CTA_MARKERS with premium-register phrases and adding a fallback
subject_line heuristic (short standalone opening line + blank line).
"""
from pipeline.agents import content_generator as cg


def test_hard_sell_style_ctas_still_detected():
    """No regression: existing marker-word CTAs must keep passing."""
    assert cg._has_element("Shop now before it's gone.", "cta")
    assert cg._has_element("Click here to learn more.", "cta")
    assert cg._has_element("Sign up today.", "cta")


def test_premium_register_ctas_now_detected():
    detected = [
        "Priority access begins Monday, exclusively for you.",
        "Your place is held; simply confirm with your personal stylist.",
        "An exclusive preview for our most valued patrons this week — by private appointment.",
        "We invite you to experience the season's final pieces in person.",
    ]
    for content in detected:
        assert cg._has_element(content, "cta"), f"expected CTA to be detected: {content!r}"


def test_subject_line_detected_without_literal_prefix():
    content = "Your Final Pieces Await\n\nAn exclusive preview for our most valued patrons."
    assert cg._has_element(content, "subject_line")


def test_subject_line_still_requires_a_short_standalone_opening_line():
    """No regression: a normal paragraph-first email (no title, no 'Subject:') is still missing."""
    content = (
        "An exclusive preview for our most valued patrons, by private "
        "appointment at your nearest boutique."
    )
    assert not cg._has_element(content, "subject_line")


def test_check_constraints_passes_email_on_premium_copy():
    constraints = cg.DEFAULT_CHANNEL_CONSTRAINTS["email"]
    content = (
        "Your Final Pieces Await\n\n"
        "An exclusive preview for our most valued patrons, by private "
        "appointment at your nearest boutique."
    )
    violations = cg._check_constraints(content, constraints)
    assert violations == []


def test_check_constraints_passes_linkedin_on_premium_copy():
    constraints = cg.DEFAULT_CHANNEL_CONSTRAINTS["linkedin"]
    content = (
        "An exclusive preview for our most valued patrons — priority access "
        "begins this week, exclusively for you."
    )
    violations = cg._check_constraints(content, constraints)
    assert violations == []
