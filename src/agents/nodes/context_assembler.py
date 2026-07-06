"""LangGraph node: assemble RAG context for all target channels via MCP retrieval tools.

Calls five MCP retrieval tools in one session:
  - retrieve_brand_guidelines  (persona_tone, cta_library, channel_template per channel)
  - retrieve_customer_segments (customer_profile)
  - retrieve_campaign_data     (ad_performance per channel)
  - retrieve_localization_rules (per non-English language)
  - get_sentiment_signal       (aggregate sentiment, no params)

All calls are deterministic — the node drives the sequence, no LLM involved here.
Results are stored in state["assembled_context"] for generate_content_node to consume.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents.state import WorkflowState
from src.rag.mcp_client import run_async
from src.utils.logger import get_logger

logger = get_logger("agents.nodes.context_assembler")

_MCP_URL         = "http://localhost:8001/mcp"
_MCP_CONNECTIONS = {"rag": {"url": _MCP_URL, "transport": "streamable_http"}}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unwrap(result: Any) -> str:
    """Extract a plain string from a langchain-mcp-adapters ainvoke result.

    langchain-mcp-adapters 0.1.0 returns a list of MCP content objects rather
    than a bare string.  Each item may be a TextContent object (with .text),
    a dict with a "text" key, or already a plain string.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, str):
            return first
        if hasattr(first, "text"):
            return first.text
        if isinstance(first, dict):
            return first.get("text", str(first))
        return str(first)
    return str(result) if result is not None else ""


def _texts(result: Any) -> list[str]:
    """Parse a retrieval tool result into a list of text snippets."""
    raw = _unwrap(result)
    try:
        docs = json.loads(raw)
        if isinstance(docs, list):
            return [d["text"] for d in docs if isinstance(d, dict) and "text" in d]
    except (json.JSONDecodeError, TypeError):
        pass
    return [raw]


def _get_tool(tools: dict, name: str):
    """Look up a tool by name, handling optional server-name prefix (e.g. 'rag__name')."""
    if name in tools:
        return tools[name]
    for key, tool in tools.items():
        if key.split("__", 1)[-1] == name:
            return tool
    raise KeyError(f"MCP tool '{name}' not found. Available: {list(tools)}")


# ── Async context builder (single MCP session) ────────────────────────────────

async def _build_context(brief: dict, persona: str | None) -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    brief_text    = brief["campaign_brief"]
    audience_text = brief["audience_segment"]
    channels      = brief["target_channels"]
    languages     = [lg for lg in brief["target_languages"] if lg != "English"]

    client = MultiServerMCPClient(_MCP_CONNECTIONS)
    tools  = {t.name: t for t in await client.get_tools()}

    # ── Shared context (same for every channel) ───────────────────────────
    persona_args = {"query": brief_text, "content_type": "persona_tone", "n_results": 3}
    if persona:
        persona_args["persona"] = persona

    persona_tone = _texts(
        await _get_tool(tools, "retrieve_brand_guidelines").ainvoke(persona_args)
    )

    cta_args = {"query": brief_text, "content_type": "cta_library", "n_results": 3}
    if persona:
        cta_args["persona"] = persona

    cta_library = _texts(
        await _get_tool(tools, "retrieve_brand_guidelines").ainvoke(cta_args)
    )

    seg_args = {"query": audience_text, "content_type": "customer_profile", "n_results": 5}
    if persona:
        seg_args["persona"] = persona

    customer_profiles = _texts(
        await _get_tool(tools, "retrieve_customer_segments").ainvoke(seg_args)
    )

    sentiment_signal = _unwrap(
        await _get_tool(tools, "get_sentiment_signal").ainvoke({})
    )

    # ── Per-channel context ───────────────────────────────────────────────
    channels_ctx: dict[str, dict] = {}
    for channel in channels:
        channel_template = _texts(
            await _get_tool(tools, "retrieve_brand_guidelines").ainvoke({
                "query":        brief_text,
                "channel":      channel,
                "content_type": "channel_template",
                "n_results":    1,
            })
        )
        ad_performance = _texts(
            await _get_tool(tools, "retrieve_campaign_data").ainvoke({
                "query":        brief_text,
                "channel":      channel,
                "content_type": "ad_performance",
                "n_results":    5,
            })
        )
        channels_ctx[channel] = {
            "channel_template": channel_template,
            "ad_performance":   ad_performance,
        }

    # ── Per-language localization (English is the default, skip it) ──────
    localization_ctx: dict[str, list[str]] = {}
    for lang in languages:
        localization_ctx[lang] = _texts(
            await _get_tool(tools, "retrieve_localization_rules").ainvoke({
                "language":  lang,
                "n_results": 3,
            })
        )

    return {
        "persona_tone":      persona_tone,
        "cta_library":       cta_library,
        "customer_profiles": customer_profiles,
        "sentiment_signal":  sentiment_signal,
        "channels":          channels_ctx,
        "localization":      localization_ctx,
    }


# ── LangGraph node ────────────────────────────────────────────────────────────

def assemble_context_node(state: WorkflowState) -> dict:
    """Retrieve RAG context for all target channels via MCP tools (deterministic)."""
    brief  = state["brief"]
    persona = state.get("persona")

    logger.info(
        "assemble_context_node — persona=%s  channels=%s  languages=%s",
        persona, brief.get("target_channels"), brief.get("target_languages"),
    )

    try:
        context = run_async(_build_context(brief, persona), timeout=120)
        logger.info(
            "assemble_context_node — done  channels=%s",
            list(context["channels"].keys()),
        )
        return {"assembled_context": context, "status": "context_assembled"}

    except Exception as exc:
        logger.error("assemble_context_node failed: %s", exc, exc_info=True)
        return {
            "assembled_context": None,
            "validation_error":  f"Context assembly failed: {exc}",
            "status":            "context_failed",
        }
