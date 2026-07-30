"""Shared intake validation helpers.

Single source of truth for injection-screening patterns, budget arithmetic,
and the ROUGH_TOKENS_PER_TASK constant.

Designed to be imported by two call sites:
  1. ``pipeline.agents.intake`` — defence-in-depth inside the graph node.
  2. ``api.routers.campaigns`` — early-422 at the API layer before enqueuing.

Both call sites must import from here.  Do not copy-paste the patterns or
arithmetic into a second location.
"""
from __future__ import annotations

import re

# Rough token estimate per generation task — used for budget pre-check.
# No LLM call is made here; this is a conservative planning heuristic.
ROUGH_TOKENS_PER_TASK = 500

# ---------------------------------------------------------------------------
# Injection-screening patterns (fail-closed)
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous\s+)?instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a\s+)", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"override\s+(system|previous)\s+(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system\s+prompt|instructions?)", re.IGNORECASE),
    re.compile(r"print\s+(the\s+)?(system\s+prompt|instructions?)", re.IGNORECASE),
    re.compile(r"repeat\s+(the\s+)?(above|system|prompt)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]


def screen_for_injection(texts: list[str]) -> list[str]:
    """Return a list of violation descriptions for any injection pattern found.

    Checks are applied across all provided text fields.  One violation per
    pattern — does not spam errors if the same pattern hits multiple times.
    """
    violations: list[str] = []
    for text in texts:
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                violations.append(
                    f"Potential instruction-injection detected "
                    f"(pattern: {pattern.pattern!r})"
                )
                break  # one hit per pattern is enough
    return violations


def estimate_task_count(
    channels: list[str],
    locales: list[str],
    audience_segments: list[str],
) -> int:
    """Return the Cartesian-product task count for a given brief's dimensions."""
    return len(channels) * len(locales) * len(audience_segments)


def check_budget(
    token_budget: int,
    channels: list[str],
    locales: list[str],
    audience_segments: list[str],
) -> list[str]:
    """Return a list of budget-violation messages, or [] if the budget is sufficient.
    
    Note: token_budget is no longer collected from users (2026-07-29); system provides
    a default high value (200k tokens) to accommodate multi-agent pipeline and tracks actual
    usage end-to-end. This validation remains as a safety check to prevent runaway costs.

    Only call this after field validation has confirmed all three lists are
    non-empty and token_budget > 0.
    """
    task_count = estimate_task_count(channels, locales, audience_segments)
    estimated_tokens = task_count * ROUGH_TOKENS_PER_TASK
    if estimated_tokens > token_budget:
        return [
            f"token_budget {token_budget} is insufficient for "
            f"{task_count} tasks × {ROUGH_TOKENS_PER_TASK} tokens "
            f"(estimated {estimated_tokens} needed)"
        ]
    return []
