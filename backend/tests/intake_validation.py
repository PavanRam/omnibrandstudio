"""Re-export shim — the canonical module has moved to pipeline.intake_validation.

Import from ``pipeline.intake_validation`` directly in all new code.
This shim exists only to avoid breaking any existing test imports.
"""
from pipeline.intake_validation import (  # noqa: F401
    ROUGH_TOKENS_PER_TASK,
    check_budget,
    estimate_task_count,
    screen_for_injection,
)
