"""Optional OpenTelemetry wiring. Enabled when OTEL_EXPORTER_OTLP_ENDPOINT
is set; otherwise this module is a no-op so dev/demo runs stay zero-config.

Install the extras:
  pip install opentelemetry-sdk opentelemetry-exporter-otlp \\
              opentelemetry-instrumentation-fastapi \\
              opentelemetry-instrumentation-httpx

Point at any OTel collector:
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
  OTEL_SERVICE_NAME=steelmind
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("steelmind.tracing")


def configure(app) -> bool:
    """Returns True if tracing was actually enabled."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning(
            "OTEL endpoint set but opentelemetry packages missing: %s — skipping", e
        )
        return False

    service_name = os.getenv("OTEL_SERVICE_NAME", "steelmind")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)

    # Best-effort httpx instrumentation so AICommander spans link to the
    # Anthropic call as a child span.
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass

    logger.info("OpenTelemetry enabled", extra={"endpoint": endpoint, "service": service_name})
    return True
