from __future__ import annotations

from typing import Optional, TypedDict


class WorkflowState(TypedDict):
    brief: dict
    system_valid: Optional[bool]
    input_scan_valid: Optional[bool]
    business_valid: Optional[bool]
    validation_error: Optional[str]
    # pending | system_failed | input_scan_failed | business_failed | approved |
    # context_failed | context_assembled | generation_failed | completed
    status: str
    # Resolved during business validation — None if audience didn't match any known persona
    persona: Optional[str]
    # Assembled RAG context keyed by section — set by assemble_context_node
    assembled_context: Optional[dict]
    # Generated content keyed by channel → language — set by generate_content_node
    generated_content: Optional[dict]
