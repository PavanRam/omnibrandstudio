"""RAG MCP server — exposes retriever tools and content generation over StreamableHTTP.

Start with:
    venv\\Scripts\\python -m src.rag.mcp_server

Serves at: http://localhost:8001/mcp
Transport: streamable_http (MCP spec 2025-03-26)
"""

import json
import os
import re
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from src.rag.retriever import RAGRetriever
from src.rag.sentiment_stats import SentimentAnalyzer
from src.utils.logger import get_logger

logger = get_logger("rag.mcp_server")

mcp = FastMCP("rag-agent", host="0.0.0.0", port=8001)

# Singletons — loaded lazily on first request.
_retriever:          Optional[RAGRetriever]      = None
_sentiment_analyzer: Optional[SentimentAnalyzer] = None
_llm = None


def _get_retriever() -> RAGRetriever:
    global _retriever
    if _retriever is None:
        logger.info("Initialising RAGRetriever (first request)...")
        _retriever = RAGRetriever()
    return _retriever


def _get_sentiment_analyzer() -> SentimentAnalyzer:
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        logger.info("Initialising SentimentAnalyzer (first request)...")
        _sentiment_analyzer = SentimentAnalyzer()
    return _sentiment_analyzer


def _get_llm():
    global _llm
    if _llm is None:
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        if provider == "groq":
            from langchain_groq import ChatGroq
            _llm = ChatGroq(
                model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                temperature=0.3,
            )
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            _llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0.3,
            )
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER '{provider}'.")
    return _llm


def _parse_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"error": "LLM returned malformed JSON", "raw": content[:300]}


@mcp.tool()
def retrieve_brand_guidelines(
    query: str,
    persona: Optional[str] = None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
    content_type: Optional[str] = None,
    n_results: int = 5,
) -> str:
    """Retrieve brand tone, channel templates, CTAs, or compliance rules.

    Args:
        query: Free-text description of what you need (e.g. "tone for luxury buyers").
        persona: Filter to one persona.
                 Valid: "High-Income Store Spender", "Budget-Conscious Low Spender",
                        "Web-Savvy Mid-Tier Buyer", "Deal-Seeking Value Hunter",
                        "Highly Engaged Campaign Responder"
        channel: Filter to one channel.
                 Valid: "Instagram", "Facebook", "LinkedIn", "Email", "Web", "Catalog"
        language: Filter to one language (use for localization_rule documents).
                  Valid: "French", "Spanish"
        content_type: Filter to one document type.
                      Valid: "brand_identity", "persona_tone", "channel_template",
                             "cta_library", "localization_rule", "compliance_rule"
        n_results: Number of results to return (default 5).

    Returns:
        JSON array string. Each element has keys: id, text, metadata, rrf_score, rerank_score.
        Pass result[i]["text"] directly into LLM prompts.
    """
    results = _get_retriever().query_brand_guidelines(
        query=query,
        n_results=n_results,
        persona=persona,
        channel=channel,
        language=language,
        content_type=content_type,
    )
    return json.dumps(results)


@mcp.tool()
def retrieve_customer_segments(
    query: str,
    persona: Optional[str] = None,
    content_type: Optional[str] = None,
    n_results: int = 5,
) -> str:
    """Retrieve customer profiles for persona-aware content personalisation.

    Args:
        query: Free-text audience description (e.g. "affluent luxury shoppers").
        persona: Filter to one persona (optional — use after mapping from audience desc).
                 Valid: "High-Income Store Spender", "Budget-Conscious Low Spender",
                        "Web-Savvy Mid-Tier Buyer", "Deal-Seeking Value Hunter",
                        "Highly Engaged Campaign Responder"
        content_type: "persona_summary" → the 5 synthetic persona descriptions
                                          (use n_results=1 for audience → persona mapping).
                      "customer_profile" → individual customer rows.
                      Omit to query both.
        n_results: Number of results to return (default 5; use 1 for persona mapping).

    Returns:
        JSON array string. Each element has keys: id, text, metadata, rrf_score, rerank_score.
        For persona mapping: result[0]["metadata"]["persona"] gives the canonical name.
    """
    results = _get_retriever().query_customer_segments(
        query=query,
        n_results=n_results,
        persona=persona,
        content_type=content_type,
    )
    return json.dumps(results)


@mcp.tool()
def retrieve_campaign_data(
    query: str,
    channel: Optional[str] = None,
    language: Optional[str] = None,
    content_type: Optional[str] = None,
    n_results: int = 5,
) -> str:
    """Retrieve campaign performance and ad data for channel/engagement context.

    Args:
        query: Free-text query (e.g. "high ROI Instagram campaigns").
        channel: Filter to one channel (optional).
                 Valid: "Instagram", "Facebook", "LinkedIn", "Email", "Web", "Catalog"
        language: Filter to one language (optional, applies to ad_performance documents only).
                  Valid: "French", "Spanish"
        content_type: "campaign_record" → customer campaign history rows.
                      "ad_performance"  → social media ad performance rows.
                      Omit to query both.
        n_results: Number of results to return (default 5).

    Returns:
        JSON array string. Each element has keys: id, text, metadata, rrf_score, rerank_score.
    """
    results = _get_retriever().query_campaign_data(
        query=query,
        n_results=n_results,
        channel=channel,
        language=language,
        content_type=content_type,
    )
    return json.dumps(results)


@mcp.tool()
def retrieve_localization_rules(
    language: str,
    n_results: int = 3,
) -> str:
    """Retrieve localization and regional guidelines for a target language.

    Args:
        language: Target language. Valid: "French", "Spanish".
                  (English is the default brand language — no rules needed.)
        n_results: Number of results to return (default 3).

    Returns:
        JSON array string. Each element has keys: id, text, metadata, rrf_score, rerank_score.
    """
    results = _get_retriever().query_brand_guidelines(
        query=f"localization rules for {language}",
        content_type="localization_rule",
        n_results=n_results,
    )
    return json.dumps(results)


@mcp.tool()
def get_sentiment_signal() -> str:
    """Return aggregate customer sentiment stats and tone recommendation.

    Pre-computed from ~16,000 labelled feedback samples. No parameters needed.
    Returns a plain-English paragraph ready to inject into content generation prompts.
    """
    return _get_sentiment_analyzer().tone_signal()


@mcp.tool()
def generate_content(
    prompt: str,
    channel: str,
    language: str = "English",
) -> str:
    """Generate on-brand marketing content using a pre-built prompt.

    The caller (generate_content_node) is responsible for assembling the full
    prompt from RAG context, brand guidelines, and brief fields. This tool
    executes the LLM call and returns the result as a JSON string.

    Args:
        prompt:   Complete content generation prompt built by the node.
        channel:  Target channel — used for logging only (Instagram, LinkedIn, etc.).
        language: Target language — used for logging only (English, French, Spanish).

    Returns:
        JSON string with channel-appropriate content fields, or
        {"error": "...", "raw": "..."} if the LLM response is malformed.
    """
    logger.info("generate_content — channel=%s  language=%s", channel, language)
    try:
        response = _get_llm().invoke(prompt)
        result   = _parse_json(response.content)
        logger.info("generate_content — success  channel=%s  language=%s", channel, language)
        return json.dumps(result)
    except Exception as exc:
        logger.error("generate_content failed: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


if __name__ == "__main__":
    logger.info("Starting RAG MCP server on http://0.0.0.0:8001/mcp")
    mcp.run(transport="streamable-http")
