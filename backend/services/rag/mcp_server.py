from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from core.config import settings
from services.rag import get_retriever

log = structlog.get_logger()

# This MCP layer is intentionally additive. Pipeline nodes keep using direct
# in-process calls for latency/reliability, while MCP enables external tool
# interoperability and cross-runtime consumers.


def _parse_json(content: str) -> dict[str, Any]:
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


async def _generate_content(prompt: str) -> dict[str, Any]:
    payload = {
        "model": "gen-free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{settings.LITELLM_BASE_URL}/v1/chat/completions", json=payload)
        response.raise_for_status()
        body = response.json()
    content = body["choices"][0]["message"]["content"]
    return _parse_json(content)


def build_mcp_app():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:
        raise RuntimeError("mcp package is required to run RAG MCP server") from exc

    mcp = FastMCP("rag-agent", host=settings.RAG_MCP_HOST, port=settings.RAG_MCP_PORT)

    @mcp.tool()
    async def retrieve_brand_guidelines(
        query: str,
        brand_id: str,
        locale: str,
        section_type: str | None = None,
        n_results: int = 5,
    ) -> str:
        chunks = await get_retriever().retrieve(
            query=query,
            brand_id=brand_id,
            locale=locale,
            section_filter=section_type,
            n_results=n_results,
        )
        return json.dumps([c.__dict__ for c in chunks])

    @mcp.tool()
    async def retrieve_customer_segments(
        query: str,
        brand_id: str,
        locale: str,
        n_results: int = 5,
    ) -> str:
        chunks = await get_retriever().query_customer_segments(
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
        )
        return json.dumps([c.__dict__ for c in chunks])

    @mcp.tool()
    async def retrieve_campaign_data(
        query: str,
        brand_id: str,
        locale: str,
        n_results: int = 5,
    ) -> str:
        chunks = await get_retriever().query_campaign_data(
            query=query,
            brand_id=brand_id,
            locale=locale,
            n_results=n_results,
        )
        return json.dumps([c.__dict__ for c in chunks])

    @mcp.tool()
    async def retrieve_localization_rules(
        language: str,
        brand_id: str,
        n_results: int = 3,
    ) -> str:
        chunks = await get_retriever().retrieve(
            query=f"localization rules for {language}",
            brand_id=brand_id,
            locale=language,
            n_results=n_results,
        )
        return json.dumps([c.__dict__ for c in chunks])

    @mcp.tool()
    async def get_sentiment_signal(
        brand_id: str,
        locale: str,
    ) -> str:
        chunks = await get_retriever().query_sentiment_insights(
            query="overall sentiment summary and signal",
            brand_id=brand_id,
            locale=locale,
            n_results=5,
        )
        if not chunks:
            return "No sentiment signal available"
        texts = "\n".join(c.content for c in chunks)
        return texts[:2000]

    @mcp.tool()
    async def generate_content(
        prompt: str,
        channel: str,
        language: str = "en-US",
    ) -> str:
        log.info("mcp_generate_content", channel=channel, language=language)
        result = await _generate_content(prompt)
        return json.dumps(result)

    return mcp


if __name__ == "__main__":
    app = build_mcp_app()
    log.info(
        "rag_mcp_server_starting",
        host=settings.RAG_MCP_HOST,
        port=settings.RAG_MCP_PORT,
        why="MCP exposed for interoperability; in-process retriever remains primary pipeline path",
    )
    app.run(transport="streamable-http")
