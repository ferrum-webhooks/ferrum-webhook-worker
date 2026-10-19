# file: app/tracing.py
#
# OpenTelemetry setup. Mirrored (with a different instrumentation set) in the worker.
#
# One trace follows an event end to end:
#   POST /events  ->  DB txn (event+deliveries+outbox)  -.
#                                                         | traceparent stored in outbox / delivery
#   relay publishes -> stream field -> worker consumes  --'
#   -> deliver (HTTP POST span) -> retry (new span, same trace, gap = backoff) -> replay
#
# Export is enabled by OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://jaeger:4318). Without it the SDK
# still creates spans (so trace ids appear in logs and traceparent is propagated) but ships nothing.

import logging
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

_configured = False


def setup_tracing(service_name: str) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    ratio = float(os.getenv("OTEL_TRACES_SAMPLER_RATIO", "1.0"))
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint and os.getenv("TESTING") != "true":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RedisInstrumentor().instrument()


def instrument_engine(engine) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    SQLAlchemyInstrumentor().instrument(engine=engine)


def tracer():
    return trace.get_tracer("ferrum")


def current_traceparent() -> Optional[str]:
    """W3C traceparent for the active span, or None if there is no valid active span."""
    carrier: dict = {}
    inject(carrier)
    return carrier.get("traceparent")


def context_from_traceparent(traceparent: Optional[str]):
    return extract({"traceparent": traceparent}) if traceparent else None


class TraceLogFilter(logging.Filter):
    """Adds trace_id to every log record so logs can be joined to traces."""
    def filter(self, record):
        ctx = trace.get_current_span().get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        return True
