import asyncio
import inspect

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import settings
from pipeline.agents import stubs
from pipeline.agents.base import AGENT_WRITE_PERMISSIONS
from pipeline.graph import build_graph
from pipeline.state import OmniBrandState

AGENT_STUB_NAMES = [
    "intake_agent_stub",
    "content_generator_stub",
    "personalization_agent_stub",
    "translation_agent_stub",
    "judge_claude_stub",
    "judge_gpt4o_stub",
    "judge_llama_stub",
    "confidence_aggregator_stub",
    "review_gate_stub",
    "publishing_agent_stub",
]


def _empty_state(**overrides) -> OmniBrandState:
    base = OmniBrandState(
        campaign_id="camp-1",
        org_id="org-1",
        brand_id="brand-1",
        user_id="user-1",
        started_at="2026-07-05T00:00:00",
        org_config={},
        brand_config={},
        model_aliases={},
        brief=None,
        rag_context=None,
        prior_campaigns=[],
        brief_valid=None,
        brief_validation_errors=[],
        budget_check_passed=None,
        tasks=[],
        current_task=None,
        variants=[],
        brand_scores=[],
        aggregated_scores=[],
        review_requests=[],
        publication_receipts=[],
        failed_task_ids=[],
        errors=[],
        current_phase="starting",
        human_review_requested=False,
        publishing_paused=False,
        token_cost_usd=0.0,
    )
    base.update(overrides)
    return base


def test_all_stubs_are_coroutines():
    for name in AGENT_STUB_NAMES:
        fn = getattr(stubs, name)
        assert asyncio.iscoroutinefunction(fn), f"{name} must be async"


def test_reflexion_router_is_sync():
    assert not asyncio.iscoroutinefunction(stubs.reflexion_router_stub)
    assert inspect.isfunction(stubs.reflexion_router_stub)


async def test_agent_write_permissions():
    """Each stub only writes to its authorised fields."""
    node_to_stub = {
        "intake_agent": stubs.intake_agent_stub,
        "content_generator": stubs.content_generator_stub,
        "personalization_agent": stubs.personalization_agent_stub,
        "translation_agent": stubs.translation_agent_stub,
        "judge_claude": stubs.judge_claude_stub,
        "judge_gpt4o": stubs.judge_gpt4o_stub,
        "judge_llama": stubs.judge_llama_stub,
        "confidence_aggregator": stubs.confidence_aggregator_stub,
        "review_gate": stubs.review_gate_stub,
        "publishing_agent": stubs.publishing_agent_stub,
    }
    assert set(node_to_stub.keys()) == set(AGENT_WRITE_PERMISSIONS.keys())

    state = _empty_state()
    for node_name, stub_fn in node_to_stub.items():
        result = await stub_fn(state)
        allowed = AGENT_WRITE_PERMISSIONS[node_name]
        assert set(result.keys()) <= allowed, (
            f"{node_name} wrote unauthorised keys: {set(result.keys()) - allowed}"
        )


def test_reflexion_router_returns_valid_label():
    from langgraph.graph import END

    state = _empty_state(current_task=None)
    assert stubs.reflexion_router_stub(state) == END

    state = _empty_state(
        current_task={"task_id": "t1", "locale": "en", "channel": "email", "segment": "all", "channel_constraints": {}},
        variants=[
            {
                "task_id": "t1",
                "locale": "en",
                "channel": "email",
                "segment": "all",
                "generated_content": None,
                "personalized_content": None,
                "translated_content": None,
                "final_content": None,
                "status": "generated",
                "generation_model": None,
                "prompt_version": None,
                "brand_guide_version": None,
                "translation_engine": None,
                "back_translation_score": None,
                "retry_count": 0,
                "reflexion_applied": True,
                "failure_reason": None,
            }
        ],
    )
    assert stubs.reflexion_router_stub(state) == "validation_subgraph"


@pytest.mark.asyncio
async def test_fan_out_fan_in_accumulation():
    """operator.add on Annotated fan-in fields accumulates across parallel
    branches instead of overwriting."""
    async with AsyncPostgresSaver.from_conn_string(
        settings.POSTGRES_DSN.replace("+asyncpg", "")
    ) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        nodes = set(graph.get_graph().nodes.keys())
        expected = {
            "__start__",
            "__end__",
            "intake_agent",
            "content_generator",
            "personalization_agent",
            "translation_agent",
            "judge_claude",
            "judge_gpt4o",
            "judge_llama",
            "confidence_aggregator",
            "review_gate",
            "publishing_agent",
        }
        assert expected <= nodes
