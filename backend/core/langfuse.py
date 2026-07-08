from typing import Any

from langfuse import Langfuse

from core.config import settings


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


def get_langfuse() -> Langfuse | NullLangfuse:
    global _client
    if _client is None:
        if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
            _client = NullLangfuse()
        else:
            try:
                _client = Langfuse(
                    host=settings.LANGFUSE_HOST,
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                )
            except Exception:
                _client = NullLangfuse()
    return _client
