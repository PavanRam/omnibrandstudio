from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pipeline.agents.aggregation import confidence_aggregator
from pipeline.agents.content_generator import content_generator
from pipeline.agents.intake import intake_agent
from pipeline.agents.personalization import personalization_agent
from pipeline.agents.review import review_gate, review_router
from pipeline.agents.stubs import (
    judge_claude_stub,
    judge_gpt4o_stub,
    judge_llama_stub,
    publishing_agent_stub,
    reflexion_router_stub,
    translation_agent_stub,
)
from pipeline.state import OmniBrandState


def post_aggregation_router(state: OmniBrandState) -> str:
    """Conditional edge after ``confidence_aggregator``.

    Precedence: an in-flight reflexion retry loops back to the judges; otherwise a
    campaign flagged for human review goes to ``review_gate`` (where the graph
    pauses via ``interrupt_before``); otherwise it proceeds straight to publishing.
    """
    if reflexion_router_stub(state) == "validation_subgraph":
        return "validation_subgraph"
    if state.get("human_review_requested"):
        return "review_gate"
    return "publishing_agent"


def build_graph(
    checkpointer=None,
    *,
    interrupt_before_review_gate: bool = True,
) -> CompiledStateGraph:
    """Build and compile the OmniBrand LangGraph pipeline.

    Flow summary:
    - Intake prepares brief context and retrieval-derived state.
    - Generation and personalization prepare candidate variants.
    - Translation fans out into three parallel judges.
    - Judge outputs fan in at confidence aggregation.
    - Router decides: reflexion retry, human review, or straight to publishing.
    - Review gate interrupts for human decisions; on resume it applies them and
      either publishes (approved/edited) or loops back to regenerate (rejected).

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.
        interrupt_before_review_gate: If true, graph pauses before review_gate
            so a human decision can be injected via checkpoint resume.

    Returns:
        CompiledStateGraph ready for ``ainvoke``/``stream`` execution.
    """
    g = StateGraph(OmniBrandState)

    g.add_node("intake_agent", intake_agent)
    g.add_node("content_generator", content_generator)
    g.add_node("personalization_agent", personalization_agent)  # T4 — real agent (was stub)
    g.add_node("translation_agent", translation_agent_stub)
    g.add_node("judge_claude", judge_claude_stub)
    g.add_node("judge_gpt4o", judge_gpt4o_stub)
    g.add_node("judge_llama", judge_llama_stub)
    g.add_node("confidence_aggregator", confidence_aggregator)  # T11 — minimal trigger (was stub)
    g.add_node("review_gate", review_gate)  # T11 — real review gate (was stub)
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

    # After aggregation: reflexion retry (→ judge_claude), human review (→ review_gate),
    # or straight to publishing. "validation_subgraph" is a logical label for the
    # reflexion loop back into the judges.
    g.add_conditional_edges(
        "confidence_aggregator",
        post_aggregation_router,
        {
            "validation_subgraph": "judge_claude",
            "review_gate": "review_gate",
            "publishing_agent": "publishing_agent",
        },
    )

    # After the (resumed) review gate: regenerate rejected variants (capped) or publish.
    g.add_conditional_edges(
        "review_gate",
        review_router,
        {
            "content_generator": "content_generator",
            "publishing_agent": "publishing_agent",
        },
    )

    g.add_edge("publishing_agent", END)

    compile_kwargs = {"checkpointer": checkpointer} if checkpointer is not None else {}
    if interrupt_before_review_gate:
        compile_kwargs["interrupt_before"] = ["review_gate"]
    return g.compile(**compile_kwargs)
