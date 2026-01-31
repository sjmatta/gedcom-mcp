"""Telemetry setup for Arize Phoenix tracing.

This module provides OpenTelemetry instrumentation for the GEDCOM MCP Server
and Strands Agent, sending traces to Arize Phoenix for observability.

Environment Variables:
    PHOENIX_ENABLED: Set to 'true' to enable tracing (default: false)
    PHOENIX_ENDPOINT: Phoenix collector URL (default: http://localhost:6006)
    PHOENIX_PROJECT_NAME: Project name in Phoenix UI (default: gedcom-server)
    OTEL_EXPORTER_OTLP_ENDPOINT: Used by Strands SDK (default: http://localhost:6006)
"""

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# OpenInference semantic conventions for Phoenix
OPENINFERENCE_SPAN_KIND = "openinference.span.kind"


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled via environment variable."""
    return os.getenv("PHOENIX_ENABLED", "false").lower() == "true"


def get_phoenix_endpoint() -> str:
    """Get the Phoenix collector endpoint."""
    return os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006")


def get_project_name() -> str:
    """Get the project name for Phoenix."""
    return os.getenv("PHOENIX_PROJECT_NAME", "gedcom-server")


class StrandsToOpenInferenceProcessor(SpanProcessor):
    """Span processor that converts Strands spans to OpenInference format.

    Phoenix uses OpenInference semantic conventions to understand span types.
    Strands uses different span naming conventions, so we map them here.

    Mappings:
        - 'chat' spans -> LLM kind
        - 'execute_tool*' spans -> TOOL kind
        - 'invoke_agent*' spans -> AGENT kind
    """

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        """Called when a span starts. Sets OpenInference span kind."""
        if not hasattr(span, "name") or not hasattr(span, "set_attribute"):
            return

        span_name = span.name.lower()

        # Map Strands span names to OpenInference kinds
        if span_name == "chat" or "chat" in span_name:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, "LLM")
        elif span_name.startswith("execute_tool") or "tool" in span_name:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, "TOOL")
        elif span_name.startswith("invoke_agent") or "agent" in span_name:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, "AGENT")
        else:
            span.set_attribute(OPENINFERENCE_SPAN_KIND, "CHAIN")

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span ends. No-op for this processor."""
        pass

    def shutdown(self) -> None:
        """Shutdown the processor."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush any buffered spans."""
        return True


_tracer_provider: TracerProvider | None = None


def initialize_tracing() -> TracerProvider | None:
    """Initialize OpenTelemetry tracing for Phoenix.

    Sets up the OTLP exporter to send traces to Phoenix and configures
    the Strands-to-OpenInference span processor.

    Returns:
        TracerProvider if tracing is enabled, None otherwise.
    """
    global _tracer_provider

    if not is_tracing_enabled():
        return None

    if _tracer_provider is not None:
        return _tracer_provider

    # Create OTLP exporter for Phoenix
    endpoint = f"{get_phoenix_endpoint()}/v1/traces"
    exporter = OTLPSpanExporter(endpoint=endpoint)

    # Create tracer provider with our custom processor
    _tracer_provider = TracerProvider()

    # Add the OpenInference processor first (modifies spans)
    _tracer_provider.add_span_processor(StrandsToOpenInferenceProcessor())

    # Add the batch exporter (sends spans to Phoenix)
    _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    # Set as global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    # Also set OTEL_EXPORTER_OTLP_ENDPOINT for Strands if not already set
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = get_phoenix_endpoint()

    return _tracer_provider


def get_tracer(name: str = "gedcom-server") -> trace.Tracer:
    """Get a tracer instance for manual instrumentation.

    Args:
        name: Name of the tracer (appears in Phoenix UI)

    Returns:
        A Tracer instance (no-op if tracing disabled)
    """
    return trace.get_tracer(name)
