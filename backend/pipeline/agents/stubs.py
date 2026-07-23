import asyncio
import re
import structlog
from langgraph.graph import END

from services.rag import get_retriever
from pipeline.state import OmniBrandState

log = structlog.get_logger()


async def _yield_once() -> None:
    await asyncio.sleep(0)


def _version_key(version: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", version)
    if match:
        return (int(match.group(1)), version)
    return (0, version)


async def intake_agent_stub(state: OmniBrandState) -> dict:
    """Intake node placeholder with real RAG context population.

    This method keeps the existing stub behavior for validation/task planning
    while replacing the hardcoded ``rag_context=None`` with a live retrieval
    attempt. Retrieval failures are intentionally non-fatal so intake can still
    progress and the pipeline can degrade gracefully.
    """
    log.info("agent_stub", agent="intake_agent", campaign_id=state.get("campaign_id"))
    rag_context = None
    brief = state.get("brief")
    query = ""
    if brief:
        query = (brief.get("objective") or "").strip() or (brief.get("raw_text") or "").strip()

    if query:
        try:
            chunks = await get_retriever().retrieve(
                query=query,
                brand_id=state["brand_id"],
                locale=(brief.get("locales") or ["en"])[0] if brief else "en",
                n_results=5,
            )
            if chunks:
                section_types = [c.section_type for c in chunks if c.section_type]
                retrieval_scores = [float(c.score) for c in chunks]
                versions = [c.version for c in chunks if c.version]
                rag_context = {
                    "brand_guide_chunks": [c.content for c in chunks],
                    "section_types": section_types,
                    "brand_guide_version": max(versions, key=_version_key) if versions else "unknown",
                    "retrieval_scores": retrieval_scores,
                }
        except Exception as exc:
            log.warning(
                "intake_rag_context_failed",
                campaign_id=state.get("campaign_id"),
                brand_id=state.get("brand_id"),
                error=str(exc),
            )

    return {
        "brief_valid": True,
        "brief_validation_errors": [],
        "budget_check_passed": True,
        "rag_context": rag_context,
        "prior_campaigns": [],
        "tasks": [],  # Stub: no tasks generated
        "current_phase": "intake_complete",
        "token_cost_usd": 0.0,
    }


async def content_generator_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="content_generator", campaign_id=state.get("campaign_id"))
    return {
        "variants": [],
        "failed_task_ids": [],
        "token_cost_usd": 0.0,
        "current_phase": "content_generated",
    }


async def personalization_agent_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="personalization_agent", campaign_id=state.get("campaign_id"))
    return {"variants": [], "token_cost_usd": 0.0}


async def translation_agent_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="translation_agent", campaign_id=state.get("campaign_id"))
    return {"variants": [], "token_cost_usd": 0.0}


async def judge_claude_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="judge_claude", campaign_id=state.get("campaign_id"))
    # token_cost_usd is a plain (non fan-in) field on OmniBrandState, so it
    # cannot be written by more than one of these three parallel branches in
    # the same super-step — omit it here; real judges should route cost
    # writes through campaign_cost_attribution (see traced_llm_call) instead.
    return {"brand_scores": []}


async def judge_gpt4o_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="judge_gpt4o", campaign_id=state.get("campaign_id"))
    return {"brand_scores": []}


async def judge_llama_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="judge_llama", campaign_id=state.get("campaign_id"))
    return {"brand_scores": []}


async def confidence_aggregator_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="confidence_aggregator", campaign_id=state.get("campaign_id"))
    return {
        "aggregated_scores": [],
        "review_requests": [],
        "human_review_requested": False,
    }


async def review_gate_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="review_gate", campaign_id=state.get("campaign_id"))
    # Preserve upstream variants; this stub only advances phase state.
    return {"current_phase": "review_complete"}


async def publishing_agent_stub(state: OmniBrandState) -> dict:
    await _yield_once()
    log.info("agent_stub", agent="publishing_agent", campaign_id=state.get("campaign_id"))
    return {
        "publication_receipts": [],
        "current_phase": "published",
    }


def reflexion_router_stub(state: OmniBrandState) -> str:
    """Synchronous conditional-edge router (not an agent node). Returns a
    label — 'validation_subgraph' routes back to judge_claude for re-scoring
    after reflexion; END otherwise (proceeds to review_gate)."""
    log.info("agent_stub", agent="reflexion_router", campaign_id=state.get("campaign_id"))
    task_id = (state.get("current_task") or {}).get("task_id")
    if not task_id:
        return END
    variant = next((v for v in state["variants"] if v["task_id"] == task_id), None)
    if variant and variant.get("reflexion_applied") and variant.get("status") == "generated":
        return "validation_subgraph"
    return END
