"""worker.main.determine_final_status — strict all-or-nothing.

2026-07-27: reversed the earlier partial-success design (2026-07-26, item 1)
per explicit user direction — this is a marketing campaign tool; a creator
asking for N channel x locale variants cannot ship with some missing or
still judge-rejected. ANY failure anywhere in the run (budget/brief invalid,
a hard-failed variant, an `errors` entry from any agent, or a variant still
judge-rejected — auto_reject, unresolved even after reflexion's one retry
round) now fails the WHOLE campaign. Nothing gets persisted on failure.
"""
from worker.main import determine_final_status


def _variant(status: str) -> dict:
    return {"task_id": f"t-{status}", "status": status}


def _agg(variant_id: str, round_: int, decision: str) -> dict:
    return {"variant_id": variant_id, "evaluation_round": round_, "routing_decision": decision}


def test_no_state_is_still_running():
    assert determine_final_status(None) == ("running", False, False)


def test_published_phase_marks_completed():
    state = {"current_phase": "published"}
    assert determine_final_status(state) == ("published", True, False)


def test_budget_failure_hard_fails_even_with_surviving_variants():
    state = {
        "budget_check_passed": False,
        "variants": [_variant("translated")],
    }
    assert determine_final_status(state) == ("failed", True, False)


def test_invalid_brief_hard_fails():
    state = {"brief_valid": False, "variants": [_variant("translated")]}
    assert determine_final_status(state) == ("failed", True, False)


def test_errors_with_zero_surviving_variants_hard_fails():
    state = {
        "errors": ["translation exhausted retries for fr-FR"],
        "variants": [_variant("translation_failed"), _variant("translation_failed")],
    }
    assert determine_final_status(state) == ("failed", True, False)


def test_errors_with_no_variants_at_all_hard_fails():
    state = {"errors": ["catastrophic failure before any variant ran"], "variants": []}
    assert determine_final_status(state) == ("failed", True, False)


def test_partial_failure_now_hard_fails_the_whole_campaign():
    """Reversed from the old regression test: 2 succeeded, 2 failed
    translation — no more half-cooked draft, the whole campaign fails."""
    state = {
        "errors": ["translation exhausted retries for fr-FR"],
        "variants": [
            _variant("translated"),
            _variant("translated"),
            _variant("translation_failed"),
            _variant("translation_failed"),
        ],
    }
    assert determine_final_status(state) == ("failed", True, False)


def test_single_failed_variant_fails_whole_campaign_even_without_errors_entry():
    """A hard-failed variant status alone (no separate `errors` entry) is
    enough — fail is a fail, regardless of which stage produced it."""
    state = {"variants": [_variant("translated"), _variant("failed")]}
    assert determine_final_status(state) == ("failed", True, False)


def test_no_errors_persists_as_draft():
    state = {"variants": [_variant("translated")]}
    assert determine_final_status(state) == ("draft", False, True)


# ── Judge-rejection exhaustion (new, 2026-07-27) ─────────────────────────────


def test_still_auto_rejected_after_reflexion_hard_fails():
    """A variant that's still auto_reject at its LATEST evaluation round
    (reflexion already ran once and judges still reject it) fails the whole
    campaign, even though variant.status itself was never set to a hard
    failure status by generation/translation."""
    state = {
        "variants": [_variant("translated")],
        "aggregated_scores": [_agg("t-translated", 0, "auto_reject")],
    }
    assert determine_final_status(state) == ("failed", True, False)


def test_stale_round_zero_rejection_ignored_once_later_round_approves():
    """round 0's auto_reject is expected/normal (that's what triggers
    reflexion) — operator.add fan-in keeps that stale entry forever, so only
    the LATEST round per variant may ever be read as the final verdict."""
    state = {
        "variants": [_variant("translated")],
        "aggregated_scores": [
            _agg("t-translated", 0, "auto_reject"),
            _agg("t-translated", 1, "auto_approve"),
        ],
    }
    assert determine_final_status(state) == ("draft", False, True)


def test_still_rejected_variant_with_no_hard_failure_status_still_fails():
    """Confirms the judge-rejection check is independent of
    _VARIANT_FAILURE_STATUSES — a variant can be judge-rejected without ever
    having a translation/generation failure status at all."""
    state = {
        "variants": [_variant("generated")],
        "aggregated_scores": [_agg("t-generated", 1, "auto_reject")],
    }
    assert determine_final_status(state) == ("failed", True, False)
