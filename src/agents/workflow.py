from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.agents.nodes.business_validator import business_validate
from src.agents.nodes.context_assembler import assemble_context_node
from src.agents.nodes.content_generator import generate_content_node
from src.agents.nodes.input_scanner import scan_input
from src.agents.nodes.system_validator import system_validate
from src.agents.state import WorkflowState


def _after_system(state: WorkflowState) -> str:
    return "scan_input" if state.get("system_valid") else "end"


def _after_input_scan(state: WorkflowState) -> str:
    return "business_validate" if state.get("input_scan_valid") else "end"


def _after_business(state: WorkflowState) -> str:
    return "assemble_context" if state.get("status") == "approved" else "end"


def _after_context(state: WorkflowState) -> str:
    return "generate_content" if state.get("status") == "context_assembled" else "end"


def build_validation_graph():
    builder = StateGraph(WorkflowState)

    builder.add_node("system_validate",   system_validate)
    builder.add_node("scan_input",        scan_input)
    builder.add_node("business_validate", business_validate)
    builder.add_node("assemble_context",  assemble_context_node)
    builder.add_node("generate_content",  generate_content_node)

    builder.set_entry_point("system_validate")

    builder.add_conditional_edges(
        "system_validate",
        _after_system,
        {"scan_input": "scan_input", "end": END},
    )
    builder.add_conditional_edges(
        "scan_input",
        _after_input_scan,
        {"business_validate": "business_validate", "end": END},
    )
    builder.add_conditional_edges(
        "business_validate",
        _after_business,
        {"assemble_context": "assemble_context", "end": END},
    )
    builder.add_conditional_edges(
        "assemble_context",
        _after_context,
        {"generate_content": "generate_content", "end": END},
    )
    builder.add_edge("generate_content", END)

    return builder.compile()


validation_graph = build_validation_graph()
