"""Telemetry setup for Arize tracing.

This module provides OpenTelemetry instrumentation for the GEDCOM MCP Server
and Strands Agent, sending traces to Arize or local Phoenix for observability.

Environment Variables:
    PHOENIX_ENABLED: Set to 'true' to enable tracing (default: false)
    PHOENIX_PROJECT_NAME: Project name in UI (default: gedcom-server)

    Arize Cloud (set both):
        ARIZE_SPACE_ID: Arize space identifier
        ARIZE_API_KEY: Arize API key

    Local Phoenix (optional):
        PHOENIX_COLLECTOR_ENDPOINT: Collector URL (default: http://localhost:6006)
"""

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider

# OpenInference semantic conventions for Phoenix
OPENINFERENCE_SPAN_KIND = "openinference.span.kind"


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled via environment variable."""
    return os.getenv("PHOENIX_ENABLED", "false").lower() == "true"


def get_phoenix_endpoint() -> str | None:
    """Get the Phoenix collector endpoint.

    Checks PHOENIX_COLLECTOR_ENDPOINT first, then legacy PHOENIX_ENDPOINT.
    Returns None if neither is set (lets register() use its default).
    """
    return os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("PHOENIX_ENDPOINT") or None


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

        # Preserve explicit kinds supplied by traced_tool or other instrumentation.
        if OPENINFERENCE_SPAN_KIND in (getattr(span, "attributes", None) or {}):
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


def _use_arize() -> bool:
    """Check if Arize Cloud credentials are configured."""
    return bool(os.getenv("ARIZE_SPACE_ID") and os.getenv("ARIZE_API_KEY"))


def initialize_tracing() -> TracerProvider | None:
    """Initialize OpenTelemetry tracing.

    Uses arize.otel.register() for Arize Cloud (when ARIZE_SPACE_ID and
    ARIZE_API_KEY are set), otherwise falls back to phoenix.otel.register()
    for local Phoenix.

    Returns:
        TracerProvider if tracing is enabled, None otherwise.
    """
    global _tracer_provider

    # Load .env before checking config, since tracing initializes before state.configure()
    from dotenv import load_dotenv

    load_dotenv()

    if not is_tracing_enabled():
        return None

    if _tracer_provider is not None:
        return _tracer_provider

    if _use_arize():
        from arize.otel import register

        provider = register(
            space_id=os.environ["ARIZE_SPACE_ID"],
            api_key=os.environ["ARIZE_API_KEY"],
            project_name=get_project_name(),
            batch=True,
            verbose=False,
        )
    else:
        from phoenix.otel import register

        provider = register(
            project_name=get_project_name(),
            endpoint=get_phoenix_endpoint(),
            batch=True,
            verbose=False,
        )

    # Add our custom processor to map Strands spans to OpenInference format.
    # Call the base OTel add_span_processor to avoid replacing the default exporter
    # (both arize and phoenix TracerProviders override add_span_processor to remove defaults).
    from opentelemetry.sdk.trace import TracerProvider as _BaseTracerProvider

    _BaseTracerProvider.add_span_processor(provider, StrandsToOpenInferenceProcessor())

    _tracer_provider = provider

    # Also set OTEL_EXPORTER_OTLP_ENDPOINT for Strands SDK if not already set
    endpoint = get_phoenix_endpoint()
    if endpoint and not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint

    return _tracer_provider


def get_tracer(name: str = "gedcom-server") -> trace.Tracer:
    """Get a tracer instance for manual instrumentation.

    Args:
        name: Name of the tracer (appears in Phoenix UI)

    Returns:
        A Tracer instance (no-op if tracing disabled)
    """
    return trace.get_tracer(name)


def traced_tool(func: Any) -> Any:
    """Decorator that wraps an MCP tool handler in an OpenTelemetry span.

    Creates a span named after the function with tool arguments as attributes.
    No-op when tracing is disabled (get_tracer returns a no-op tracer).
    """
    import functools
    import json

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer()
        with tracer.start_as_current_span(
            func.__name__,
            attributes={
                OPENINFERENCE_SPAN_KIND: "TOOL",
                "tool.name": func.__name__,
                "tool.parameters": json.dumps(kwargs, default=str),
            },
        ) as span:
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                raise

    return wrapper
