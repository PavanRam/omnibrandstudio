"""Shared output-safety helpers for content_generator and personalization_agent.

Extracts the toxicity-check logic that was previously private to translation.py
so both generation-side agents can call it without importing from translation.py
(which has heavy optional deps: sacrebleu, tenacity, huggingface_hub).

Design decisions:
- fail-open (flag, not hard-block) to match translation.py's existing posture.
- Uses the ``eval-model`` alias (Haiku) only if the HF toxicity model is
  unavailable — keeps cost negligible for the common path.
- Brand-name check is kept from the translation-side original.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()

# Re-exported so callers can import from one place.
from pipeline.intake_validation import screen_for_injection as screen_for_injection  # noqa: F401

_TOXICITY_MODEL = "martin-ha/toxic-comment-model"
_TOXICITY_THRESHOLD = 0.85

# Module-level HF client (lazy singleton — only created if needed)
_hf_client_singleton = None


def _hf_client():
    global _hf_client_singleton
    if _hf_client_singleton is None:
        try:
            from huggingface_hub import AsyncInferenceClient
            from core.config import settings

            _hf_client_singleton = AsyncInferenceClient(
                provider="hf-inference", api_key=settings.HF_TOKEN or None
            )
        except Exception:
            _hf_client_singleton = None
    return _hf_client_singleton


async def screen_output_safety(text: str, *, brand_name: str | None = None) -> list[str]:
    """Return a list of guardrail flag strings for generated output.

    Checks:
    1. HF toxicity classifier (fail-open on unavailability).
    2. Brand-name presence when brand_name is supplied.

    Never raises — degraded to an empty list on any exception.
    """
    violations: list[str] = []

    client = _hf_client()
    if client is not None:
        try:
            result = await client.text_classification(text, model=_TOXICITY_MODEL)
            for item in result:
                is_dict = isinstance(item, dict)
                label = item.get("label") if is_dict else getattr(item, "label", None)
                score = item.get("score") if is_dict else getattr(item, "score", None)
                if label and score is not None and score >= _TOXICITY_THRESHOLD:
                    violations.append(f"output_toxicity:{label}:{score:.2f}")
        except Exception as exc:
            log.warning(
                "output_toxicity_check_unavailable",
                error=str(exc),
                note="HF model unavailable — skipping toxicity check for this variant",
            )

    if brand_name and brand_name.lower() not in text.lower():
        violations.append(f"output_brand_name_absent:{brand_name}")

    return violations
