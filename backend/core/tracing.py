"""
OpenTelemetry bootstrap.

Call ``setup_observability(service_name)`` once at process start (FastAPI
lifespan or worker main).  Call ``instrument_fastapi(app)`` separately in
the FastAPI lifespan *after* the app is created.

Both functions are no-ops when OTEL_ENABLED=False.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger()

_initialised = False


def setup_observability(service_name: str) -> None:
    """Initialise OTLP trace export and auto-instrument HTTPX, DB, Redis.

    Idempotent — safe to call more than once.
    """
    global _initialised
    if _initialised:
        return

    from core.config import settings  # late import — avoids circular at module load

    if not settings.OTEL_ENABLED:
        log.info("otel_disabled", service=service_name)
        _initialised = True
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: "0.1.0",
        "deployment.environment": settings.APP_ENV,
    })

    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=True,
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _wire_auto_instrumentation()

    log.info(
        "otel_initialised",
        service=service_name,
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
    _initialised = True


def instrument_fastapi(app: Any) -> None:
    """Instrument a FastAPI *app* instance.  Must be called after setup_observability()."""
    from core.config import settings
    if not settings.OTEL_ENABLED:
        return
    _try_instrument("FastAPI", lambda: _do_instrument_fastapi(app))


def _do_instrument_fastapi(app: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


def _wire_auto_instrumentation() -> None:
    _try_instrument("HTTPX",       _instrument_httpx)
    _try_instrument("SQLAlchemy",  _instrument_sqlalchemy)
    _try_instrument("Redis",       _instrument_redis)


def _try_instrument(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        log.debug("otel_auto_instrumented", library=name)
    except Exception as exc:  # noqa: BLE001
        log.debug("otel_auto_instrument_skipped", library=name, reason=str(exc))


def _instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HTTPXClientInstrumentor().instrument()


def _instrument_sqlalchemy() -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    SQLAlchemyInstrumentor().instrument()


def _instrument_redis() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RedisInstrumentor().instrument()


def get_tracer(name: str) -> Any:
    """Return a named OTel tracer (no-op tracer when OTel is disabled)."""
    from opentelemetry import trace
    return trace.get_tracer(name)
