import structlog
from langgraph.graph import END

from pipeline.state import OmniBrandState

log = structlog.get_logger()


async def intake_agent_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="intake_agent", campaign_id=state.get("campaign_id"))
    return {
        "brief_valid": True,
        "brief_validation_errors": [],
        "budget_check_passed": True,
        "rag_context": None,
        "prior_campaigns": [],
        "tasks": [],  # Stub: no tasks generated
        "current_phase": "intake_complete",
        "token_cost_usd": 0.0,
    }


async def content_generator_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="content_generator", campaign_id=state.get("campaign_id"))
    return {
        "variants": [],
        "failed_task_ids": [],
        "token_cost_usd": 0.0,
        "current_phase": "content_generated",
    }


async def personalization_agent_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="personalization_agent", campaign_id=state.get("campaign_id"))
    return {"variants": [], "token_cost_usd": 0.0}


async def translation_agent_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="translation_agent", campaign_id=state.get("campaign_id"))
    return {"variants": [], "token_cost_usd": 0.0}


async def judge_claude_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="judge_claude", campaign_id=state.get("campaign_id"))
    # token_cost_usd is a plain (non fan-in) field on OmniBrandState, so it
    # cannot be written by more than one of these three parallel branches in
    # the same super-step — omit it here; real judges should route cost
    # writes through campaign_cost_attribution (see traced_llm_call) instead.
    return {"brand_scores": []}


async def judge_gpt4o_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="judge_gpt4o", campaign_id=state.get("campaign_id"))
    return {"brand_scores": []}


async def judge_llama_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="judge_llama", campaign_id=state.get("campaign_id"))
    return {"brand_scores": []}


async def confidence_aggregator_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="confidence_aggregator", campaign_id=state.get("campaign_id"))
    return {
        "aggregated_scores": [],
        "review_requests": [],
        "human_review_requested": False,
    }


async def review_gate_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="review_gate", campaign_id=state.get("campaign_id"))
    return {"variants": [], "current_phase": "review_complete"}


async def publishing_agent_stub(state: OmniBrandState) -> dict:
    log.info("agent_stub", agent="publishing_agent", campaign_id=state.get("campaign_id"))
    return {
        "publication_receipts": [],
        "variants": [],
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
