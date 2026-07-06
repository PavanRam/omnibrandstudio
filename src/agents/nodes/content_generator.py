"""LangGraph node: generate on-brand content per channel via MCP generate_content tool.

Owns all prompt-building logic. For each (channel, language) combination it:
  1. Pulls the relevant slices of assembled_context from state.
  2. Builds a complete LLM prompt.
  3. Calls the generate_content MCP tool (which executes the LLM call server-side).
  4. Stores the parsed result in state["generated_content"][channel][language].

The node is fully deterministic — it drives the loop, the MCP tool runs the LLM.
"""
from __future__ import annotations

import json

from src.agents.state import WorkflowState
from src.rag.mcp_client import run_async
from src.utils.logger import get_logger

logger = get_logger("agents.nodes.content_generator")

_MCP_URL         = "http://localhost:8001/mcp"
_MCP_CONNECTIONS = {"rag": {"url": _MCP_URL, "transport": "streamable_http"}}

_SEP = "\n---\n"

# ── Prompt templates ──────────────────────────────────────────────────────────

_CONTENT_PROMPT = """\
You are a brand content writer for Omnibrand Studio, a premium lifestyle and consumer \
goods brand. Write a {channel} marketing post for the campaign below.

## Campaign
Brief: {campaign_brief}
Goal: {campaign_goal}
Brand Tone: {brand_tone}
Target Persona: {persona}
Restricted words (never use): {restricted_words}

## Tone & Voice Guidelines
{persona_tone_guidelines}

## Channel Format Requirements
{channel_format_spec}

## Target Audience Profile
{customer_profile_summary}

## What Has Worked on {channel} (Reference — do not copy verbatim)
{top_performing_ads}

## CTA Options
{cta_options}

## Customer Sentiment Context
{sentiment_context}
{localization_section}
## Grounding Rules
- Base every claim, statistic, feature, or benefit strictly on the sections above. \
Do not invent facts, numbers, product details, or customer quotes that are not \
supported by them.
- If the context above does not cover something you would normally mention, write \
around it in generic on-brand language instead of fabricating specifics.
- Treat the restricted words list as a hard constraint — do not use those words or \
close variants anywhere in the output.

Return raw JSON only — no explanation, no markdown fences.

Instagram / Facebook → {{"headline": "...", "body": "...", "hashtags": ["..."], "cta": "..."}}
LinkedIn            → {{"headline": "...", "body": "...", "cta": "..."}}
Email               → {{"subject": "...", "preview_text": "...", "body": "...", "cta": "..."}}
Web                 → {{"headline": "...", "subheadline": "...", "body": "...", "cta": "..."}}
Catalog             → {{"title": "...", "description": "...", "cta": "..."}}
"""

_LOCALIZATION_SECTION = """\

## Localization
Language: {language}
Write the entire output in {language}. Follow these regional rules strictly:
{localization_rules}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unwrap(result) -> str:
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


def _join(texts: list[str]) -> str:
    return _SEP.join(texts) if texts else "No data available."


def _get_tool(tools: dict, name: str):
    if name in tools:
        return tools[name]
    for key, tool in tools.items():
        if key.split("__", 1)[-1] == name:
            return tool
    raise KeyError(f"MCP tool '{name}' not found. Available: {list(tools)}")


def _build_prompt(
    channel: str,
    language: str,
    brief: dict,
    persona: str,
    assembled_context: dict,
) -> str:
    ch_ctx = assembled_context["channels"].get(channel, {})

    loc_rules = _join(assembled_context.get("localization", {}).get(language, []))
    loc_section = (
        _LOCALIZATION_SECTION.format(language=language, localization_rules=loc_rules)
        if language != "English"
        else ""
    )

    return _CONTENT_PROMPT.format(
        channel=channel,
        campaign_brief=brief["campaign_brief"],
        campaign_goal=brief["campaign_goal"],
        brand_tone=brief["brand_tone"],
        persona=persona,
        restricted_words=", ".join(brief.get("restricted_words", [])) or "none",
        persona_tone_guidelines=_join(assembled_context["persona_tone"]),
        channel_format_spec=_join(ch_ctx.get("channel_template", [])),
        customer_profile_summary=_join(assembled_context["customer_profiles"]),
        top_performing_ads=_join(ch_ctx.get("ad_performance", [])),
        cta_options=_join(assembled_context["cta_library"]),
        sentiment_context=assembled_context["sentiment_signal"],
        localization_section=loc_section,
    )


# ── Async generator (single MCP session for all channels × languages) ─────────

async def _generate_all(
    brief: dict,
    persona: str,
    assembled_context: dict,
) -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    channels  = brief["target_channels"]
    languages = brief["target_languages"]
    generated: dict[str, dict] = {}

    client   = MultiServerMCPClient(_MCP_CONNECTIONS)
    tools    = {t.name: t for t in await client.get_tools()}
    gen_tool = _get_tool(tools, "generate_content")

    for channel in channels:
        generated[channel] = {}
        for language in languages:
            prompt = _build_prompt(channel, language, brief, persona, assembled_context)

            raw = _unwrap(await gen_tool.ainvoke({
                "prompt":   prompt,
                "channel":  channel,
                "language": language,
            }))

            try:
                generated[channel][language] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                generated[channel][language] = {"raw": raw}

            logger.info(
                "generate_content_node — done  channel=%s  language=%s",
                channel, language,
            )

    return generated


# ── LangGraph node ────────────────────────────────────────────────────────────

def generate_content_node(state: WorkflowState) -> dict:
    """Generate on-brand content for every (channel, language) pair via MCP."""
    brief             = state["brief"]
    persona           = state.get("persona") or "General Audience"
    assembled_context = state.get("assembled_context") or {}

    logger.info(
        "generate_content_node — persona=%s  channels=%s  languages=%s",
        persona, brief.get("target_channels"), brief.get("target_languages"),
    )

    try:
        content = run_async(
            _generate_all(brief, persona, assembled_context),
            timeout=180,
        )
        logger.info(
            "generate_content_node — completed  channels=%s", list(content.keys())
        )
        return {"generated_content": content, "status": "completed"}

    except Exception as exc:
        logger.error("generate_content_node failed: %s", exc, exc_info=True)
        return {
            "generated_content": None,
            "validation_error":  f"Content generation failed: {exc}",
            "status":            "generation_failed",
        }
