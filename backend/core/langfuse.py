from typing import Any

from langfuse import Langfuse
import structlog

from core.config import settings


log = structlog.get_logger()


class NullLangfuse:
    """No-op stand-in used when Langfuse keys are absent/placeholder, so the
    app can boot and traced_llm_call() can call trace() unconditionally."""

    def trace(self, *args: Any, **kwargs: Any) -> "NullLangfuse":
        return self

    def span(self, *args: Any, **kwargs: Any) -> "NullLangfuse":
        return self

    def generation(self, *args: Any, **kwargs: Any) -> "NullLangfuse":
        return self

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None

    def end(self, *args: Any, **kwargs: Any) -> None:
        return None

    def flush(self) -> None:
        return None


_client: Langfuse | NullLangfuse | None = None


def start_langfuse_trace(
    *,
    name: str,
    session_id: str | None,
    metadata: dict[str, Any],
) -> Any:
    """Create a trace-like handle across Langfuse SDK variants.

    Some SDK versions expose trace(), while others may expose generation().
    This helper normalizes both shapes to a handle that supports update()/end().
    """
    client = get_langfuse()

    trace_fn = getattr(client, "trace", None)
    if callable(trace_fn):
        try:
            return trace_fn(name=name, session_id=session_id, metadata=metadata)
        except Exception:
            return NullLangfuse()

    generation_fn = getattr(client, "generation", None)
    if callable(generation_fn):
        try:
            return generation_fn(
                name=name,
                model=str(metadata.get("model", "")),
                input={"session_id": session_id, **metadata},
            )
        except Exception:
            return NullLangfuse()

    log.warning("langfuse_trace_api_unavailable", name=name)
    return NullLangfuse()


def get_langfuse() -> Langfuse | NullLangfuse:
    global _client
    if _client is None:
        if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
            log.warning("langfuse_disabled_missing_keys", host=settings.LANGFUSE_HOST)
            _client = NullLangfuse()
        else:
            try:
                _client = Langfuse(
                    host=settings.LANGFUSE_HOST,
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                )
                log.info(
                    "langfuse_initialized",
                    host=settings.LANGFUSE_HOST,
                    public_key_prefix=settings.LANGFUSE_PUBLIC_KEY[:8],
                )
            except Exception:
                log.warning("langfuse_init_failed_fallback", host=settings.LANGFUSE_HOST)
                _client = NullLangfuse()
    return _client
