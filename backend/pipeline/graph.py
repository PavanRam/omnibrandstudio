from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pipeline.agents.content_generator import content_generator
from pipeline.agents.personalization import personalization_agent
from pipeline.agents.stubs import (
    confidence_aggregator_stub,
    intake_agent_stub,
    judge_claude_stub,
    judge_gpt4o_stub,
    judge_llama_stub,
    publishing_agent_stub,
    reflexion_router_stub,
    review_gate_stub,
    translation_agent_stub,
)
from pipeline.state import OmniBrandState


def build_graph(
    checkpointer=None,
    *,
    interrupt_before_review_gate: bool = True,
) -> CompiledStateGraph:
    g = StateGraph(OmniBrandState)

    g.add_node("intake_agent", intake_agent_stub)
    g.add_node("content_generator", content_generator)
    g.add_node("personalization_agent", personalization_agent)  # T4 — real agent (was stub)
    g.add_node("translation_agent", translation_agent_stub)
    g.add_node("judge_claude", judge_claude_stub)
    g.add_node("judge_gpt4o", judge_gpt4o_stub)
    g.add_node("judge_llama", judge_llama_stub)
    g.add_node("confidence_aggregator", confidence_aggregator_stub)
    g.add_node("review_gate", review_gate_stub)
    g.add_node("publishing_agent", publishing_agent_stub)

    g.set_entry_point("intake_agent")
    g.add_edge("intake_agent", "content_generator")
    g.add_edge("content_generator", "personalization_agent")
    g.add_edge("personalization_agent", "translation_agent")
    g.add_edge("translation_agent", "judge_claude")
    g.add_edge("translation_agent", "judge_gpt4o")
    g.add_edge("translation_agent", "judge_llama")
    g.add_edge("judge_claude", "confidence_aggregator")
    g.add_edge("judge_gpt4o", "confidence_aggregator")
    g.add_edge("judge_llama", "confidence_aggregator")

    # reflexion_router_stub is a routing function, not a node — it is used
    # directly as the conditional-edge selector. "validation_subgraph" is a
    # logical label mapped to the real "judge_claude" node; END proceeds.
    g.add_conditional_edges(
        "confidence_aggregator",
        reflexion_router_stub,
        {"validation_subgraph": "judge_claude", END: "review_gate"},
    )

    g.add_edge("review_gate", "publishing_agent")
    g.add_edge("publishing_agent", END)

    compile_kwargs = {"checkpointer": checkpointer} if checkpointer is not None else {}
    if interrupt_before_review_gate:
        compile_kwargs["interrupt_before"] = ["review_gate"]
    return g.compile(**compile_kwargs)
