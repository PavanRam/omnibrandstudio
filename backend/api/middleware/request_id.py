"""
Request ID middleware.

Accepts an inbound X-Request-ID header when it is a valid UUID; otherwise
generates a fresh UUIDv7.  Every request then has a stable, unique ID that:

  • lives at  request.state.request_id
  • is bound to the structlog context-vars so every log line in the request
    automatically carries the field
  • is echoed back in the X-Request-ID response header

This middleware must be added *before* any router in main.py so that the
request_id is available to all downstream handlers and exception handlers.
"""
from __future__ import annotations

from typing import Any

import structlog
from starlette.datastructures import State
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from core.ids import is_valid_uuid, new_request_id

log = structlog.get_logger()


class RequestIDMiddleware:
    """Lightweight, dependency-free ASGI middleware for request ID propagation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Bootstrap Starlette state so downstream code can access request.state
        if "state" not in scope:
            scope["state"] = State()  # type: ignore[assignment]

        request = Request(scope, receive)
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if (incoming and is_valid_uuid(incoming)) else new_request_id()

        # Make accessible via  request.state.request_id
        request.state.request_id = request_id  # type: ignore[attr-defined]

        # Bind to structlog context-vars — visible in all log lines for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def _send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, _send_with_header)
        finally:
            structlog.contextvars.clear_contextvars()
