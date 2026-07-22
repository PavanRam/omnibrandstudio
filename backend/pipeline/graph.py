from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pipeline.agents.aggregator import confidence_aggregator
from pipeline.agents.content_generator import content_generator
from pipeline.agents.intake import intake_agent
from pipeline.agents.judge_planner import judge_gate, judge_gate_router
from pipeline.agents.judges import judge_claude, judge_gpt4o, judge_llama
from pipeline.agents.personalization import personalization_agent
from pipeline.agents.reflexion import reflexion, reflexion_router
from pipeline.agents.stubs import (
    publishing_agent_stub,
    review_gate_stub,
)
from pipeline.agents.translation import translation_agent
from pipeline.state import OmniBrandState


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
    - Router decides whether to re-enter validation or continue.
    - Review gate can interrupt for human decisions before publishing.

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.
        interrupt_before_review_gate: If true, graph pauses before review_gate
            so human review can be injected via checkpoint resume.

    Returns:
        CompiledStateGraph ready for ``ainvoke``/``stream`` execution.
    """
    g = StateGraph(OmniBrandState)

    g.add_node("intake_agent", intake_agent)
    g.add_node("content_generator", content_generator)
    g.add_node("personalization_agent", personalization_agent)  # T4 — real agent (was stub)
    g.add_node("translation_agent", translation_agent)  # T5 — real agent (was stub)
    g.add_node("judge_gate", judge_gate)  # T3b — intelligent judge gating
    g.add_node("judge_claude", judge_claude)  # T3c — real judge (was stub)
    g.add_node("judge_gpt4o", judge_gpt4o)  # T3c — real judge (was stub)
    g.add_node("judge_llama", judge_llama)  # T3c — real judge (was stub)
    g.add_node("confidence_aggregator", confidence_aggregator)  # T3g — real (was stub)
    g.add_node("reflexion", reflexion)  # T3f — self-correction retry
    g.add_node("review_gate", review_gate_stub)
    g.add_node("publishing_agent", publishing_agent_stub)

    g.set_entry_point("intake_agent")
    g.add_edge("intake_agent", "content_generator")
    g.add_edge("content_generator", "personalization_agent")
    g.add_edge("personalization_agent", "translation_agent")

    # Judge gate decides the panel size (full / lite / skip) before fan-out.
    g.add_edge("translation_agent", "judge_gate")
    g.add_conditional_edges(
        "judge_gate",
        judge_gate_router,
        ["judge_claude", "judge_gpt4o", "judge_llama", "review_gate"],
    )
    g.add_edge("judge_claude", "confidence_aggregator")
    g.add_edge("judge_gpt4o", "confidence_aggregator")
    g.add_edge("judge_llama", "confidence_aggregator")

    # Aggregator hands off to the reflexion node, which regenerates any failing
    # variant in place. The router then either re-fans the corrected variant
    # back through the judge panel (one retry) or proceeds to the review gate.
    g.add_edge("confidence_aggregator", "reflexion")
    g.add_conditional_edges(
        "reflexion",
        reflexion_router,
        ["judge_claude", "judge_gpt4o", "judge_llama", "review_gate"],
    )

    g.add_edge("review_gate", "publishing_agent")
    g.add_edge("publishing_agent", END)

    compile_kwargs = {"checkpointer": checkpointer} if checkpointer is not None else {}
    if interrupt_before_review_gate:
        compile_kwargs["interrupt_before"] = ["review_gate"]
    return g.compile(**compile_kwargs)
