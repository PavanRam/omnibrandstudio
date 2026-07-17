from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog

log = structlog.get_logger()

# We keep this bridge only for interoperability with sync callers. The primary
# application path remains direct async in-process retrieval through services.rag.
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()
log.info("rag_mcp_bridge_started", thread_id=_loop_thread.ident)


def run_async(coro: Any, timeout: int = 120) -> Any:
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError as exc:
        raise RuntimeError(f"MCP call timed out after {timeout}s") from exc
