"""Tests for telemetry module."""

import os
from unittest.mock import MagicMock, patch


class TestIsTracingEnabled:
    """Tests for is_tracing_enabled function."""

    def test_disabled_by_default(self):
        """Tracing should be disabled when env var is not set."""
        from gedcom_server.telemetry import is_tracing_enabled

        with patch.dict(os.environ, {}, clear=True):
            # Remove the var if it exists
            os.environ.pop("PHOENIX_ENABLED", None)
            assert is_tracing_enabled() is False

    def test_disabled_when_false(self):
        """Tracing should be disabled when explicitly set to false."""
        from gedcom_server.telemetry import is_tracing_enabled

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "false"}):
            assert is_tracing_enabled() is False

    def test_enabled_when_true(self):
        """Tracing should be enabled when set to true."""
        from gedcom_server.telemetry import is_tracing_enabled

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "true"}):
            assert is_tracing_enabled() is True

    def test_enabled_case_insensitive(self):
        """PHOENIX_ENABLED should be case-insensitive."""
        from gedcom_server.telemetry import is_tracing_enabled

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "TRUE"}):
            assert is_tracing_enabled() is True

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "True"}):
            assert is_tracing_enabled() is True


class TestGetPhoenixEndpoint:
    """Tests for get_phoenix_endpoint function."""

    def test_default_endpoint(self):
        """Should return default endpoint when not configured."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHOENIX_ENDPOINT", None)
            assert get_phoenix_endpoint() == "http://localhost:6006"

    def test_custom_endpoint(self):
        """Should return custom endpoint when configured."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(os.environ, {"PHOENIX_ENDPOINT": "http://phoenix.example.com:8080"}):
            assert get_phoenix_endpoint() == "http://phoenix.example.com:8080"


class TestGetProjectName:
    """Tests for get_project_name function."""

    def test_default_project_name(self):
        """Should return default project name when not configured."""
        from gedcom_server.telemetry import get_project_name

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHOENIX_PROJECT_NAME", None)
            assert get_project_name() == "gedcom-server"

    def test_custom_project_name(self):
        """Should return custom project name when configured."""
        from gedcom_server.telemetry import get_project_name

        with patch.dict(os.environ, {"PHOENIX_PROJECT_NAME": "my-genealogy-app"}):
            assert get_project_name() == "my-genealogy-app"


class TestStrandsToOpenInferenceProcessor:
    """Tests for StrandsToOpenInferenceProcessor span processor."""

    def test_chat_span_mapped_to_llm(self):
        """Chat spans should be mapped to LLM kind."""
        from gedcom_server.telemetry import (
            OPENINFERENCE_SPAN_KIND,
            StrandsToOpenInferenceProcessor,
        )

        processor = StrandsToOpenInferenceProcessor()
        mock_span = MagicMock()
        mock_span.name = "chat"

        processor.on_start(mock_span)

        mock_span.set_attribute.assert_called_with(OPENINFERENCE_SPAN_KIND, "LLM")

    def test_execute_tool_span_mapped_to_tool(self):
        """execute_tool spans should be mapped to TOOL kind."""
        from gedcom_server.telemetry import (
            OPENINFERENCE_SPAN_KIND,
            StrandsToOpenInferenceProcessor,
        )

        processor = StrandsToOpenInferenceProcessor()
        mock_span = MagicMock()
        mock_span.name = "execute_tool_get_biography"

        processor.on_start(mock_span)

        mock_span.set_attribute.assert_called_with(OPENINFERENCE_SPAN_KIND, "TOOL")

    def test_invoke_agent_span_mapped_to_agent(self):
        """invoke_agent spans should be mapped to AGENT kind."""
        from gedcom_server.telemetry import (
            OPENINFERENCE_SPAN_KIND,
            StrandsToOpenInferenceProcessor,
        )

        processor = StrandsToOpenInferenceProcessor()
        mock_span = MagicMock()
        mock_span.name = "invoke_agent_main"

        processor.on_start(mock_span)

        mock_span.set_attribute.assert_called_with(OPENINFERENCE_SPAN_KIND, "AGENT")

    def test_unknown_span_mapped_to_chain(self):
        """Unknown spans should be mapped to CHAIN kind."""
        from gedcom_server.telemetry import (
            OPENINFERENCE_SPAN_KIND,
            StrandsToOpenInferenceProcessor,
        )

        processor = StrandsToOpenInferenceProcessor()
        mock_span = MagicMock()
        mock_span.name = "some_other_operation"

        processor.on_start(mock_span)

        mock_span.set_attribute.assert_called_with(OPENINFERENCE_SPAN_KIND, "CHAIN")

    def test_on_end_is_noop(self):
        """on_end should not raise any errors."""
        from gedcom_server.telemetry import StrandsToOpenInferenceProcessor

        processor = StrandsToOpenInferenceProcessor()
        mock_span = MagicMock()

        # Should not raise
        processor.on_end(mock_span)

    def test_force_flush_returns_true(self):
        """force_flush should return True."""
        from gedcom_server.telemetry import StrandsToOpenInferenceProcessor

        processor = StrandsToOpenInferenceProcessor()
        assert processor.force_flush() is True

    def test_shutdown_is_noop(self):
        """shutdown should not raise any errors."""
        from gedcom_server.telemetry import StrandsToOpenInferenceProcessor

        processor = StrandsToOpenInferenceProcessor()
        # Should not raise
        processor.shutdown()


class TestInitializeTracing:
    """Tests for initialize_tracing function."""

    def test_returns_none_when_disabled(self):
        """Should return None when tracing is disabled."""
        from gedcom_server.telemetry import initialize_tracing

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "false"}):
            result = initialize_tracing()
            assert result is None

    @patch("gedcom_server.telemetry.OTLPSpanExporter")
    @patch("gedcom_server.telemetry.trace.set_tracer_provider")
    def test_initializes_when_enabled(self, mock_set_provider, mock_exporter):
        """Should initialize tracer provider when enabled."""
        # Reset the global state for this test
        import gedcom_server.telemetry as telemetry_module

        telemetry_module._tracer_provider = None

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "true"}):
            result = telemetry_module.initialize_tracing()

            assert result is not None
            mock_set_provider.assert_called_once()
            mock_exporter.assert_called_once_with(endpoint="http://localhost:6006/v1/traces")

        # Reset for other tests
        telemetry_module._tracer_provider = None

    @patch("gedcom_server.telemetry.OTLPSpanExporter")
    @patch("gedcom_server.telemetry.trace.set_tracer_provider")
    def test_sets_otel_endpoint_if_not_set(self, mock_set_provider, mock_exporter):
        """Should set OTEL_EXPORTER_OTLP_ENDPOINT if not already set."""
        import gedcom_server.telemetry as telemetry_module

        telemetry_module._tracer_provider = None

        env = {"PHOENIX_ENABLED": "true", "PHOENIX_ENDPOINT": "http://custom:9999"}
        # Ensure OTEL var is not set
        env_cleared = {k: v for k, v in os.environ.items() if k != "OTEL_EXPORTER_OTLP_ENDPOINT"}
        env_cleared.update(env)

        with patch.dict(os.environ, env_cleared, clear=True):
            telemetry_module.initialize_tracing()
            assert os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") == "http://custom:9999"

        # Reset for other tests
        telemetry_module._tracer_provider = None
