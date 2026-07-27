"""Publishing email's Brand Score block (2026-07-27) — weighted_mean is
stored on a 0-to-1 scale (aggregator.py's `mean_01`); the email template
must convert it to the same 0-to-10 scale everything else in the block
uses (judge_scores, the gauge bar), not display/size the gauge as if it
were already 0-to-10.
"""
from __future__ import annotations

from pipeline.agents.email_templates import _render_score_block


def _score(**overrides) -> dict:
    base = {
        "weighted_mean": 0.6,
        "judge_scores": [6.2, 5.0, 6.2],
        "routing_decision": "auto_reject",
        "critical_violations": [],
        "consensus_level": "medium",
        "degraded_mode": False,
    }
    base.update(overrides)
    return base


def test_weighted_mean_rendered_on_0_to_10_scale_not_0_to_1() -> None:
    """Regression: a real 0.6/1.0 weighted mean (≈ the judges' own 6.2/5.0/6.2
    average) previously rendered as "0.6/10" with a 6%-wide gauge instead of
    "6.0/10" with a 60%-wide gauge — found live in a real published email."""
    html = _render_score_block(_score(weighted_mean=0.6))

    assert "6.0<span" in html  # the composite value, formatted to 1 decimal
    assert "0.6<span" not in html
    assert "width:60%" in html


def test_perfect_weighted_mean_renders_as_ten_out_of_ten() -> None:
    html = _render_score_block(_score(weighted_mean=1.0))

    assert "10.0<span" in html
    assert "width:100%" in html


def test_zero_weighted_mean_renders_as_zero() -> None:
    html = _render_score_block(_score(weighted_mean=0.0))

    assert "0.0<span" in html
    assert "width:0%" in html


def test_no_score_renders_fallback_message() -> None:
    html = _render_score_block(None)

    assert "Brand scores not available" in html
