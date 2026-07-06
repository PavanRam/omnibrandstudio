"""Background event loop bridge — call async MCP tools from sync LangGraph nodes.

LangGraph nodes are synchronous Python functions; the langchain-mcp-adapters
MultiServerMCPClient is async-only.  This module starts a single daemon thread
with a dedicated event loop so nodes can submit coroutines via run_async()
without triggering "event loop already running" conflicts with Streamlit.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from src.utils.logger import get_logger

logger = get_logger("rag.mcp_client")

_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()
logger.debug("MCP background event loop started (thread=%d)", _loop_thread.ident)


def run_async(coro: Any, timeout: int = 120) -> Any:
    """Submit a coroutine to the background event loop and block until done.

    Args:
        coro:    Awaitable coroutine to execute.
        timeout: Seconds before raising RuntimeError.

    Returns:
        Whatever the coroutine returns.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        raise RuntimeError(f"MCP call timed out after {timeout}s")
