"""Tests for telemetry module."""

import os
from unittest.mock import MagicMock, patch


class TestIsTracingEnabled:
    """Tests for is_tracing_enabled function."""

    def test_disabled_by_default(self):
        """Tracing should be disabled when env var is not set."""
        from gedcom_server.telemetry import is_tracing_enabled

        with patch.dict(os.environ, {}, clear=True):
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

    def test_returns_none_when_not_configured(self):
        """Should return None when no endpoint env vars are set."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHOENIX_COLLECTOR_ENDPOINT", None)
            os.environ.pop("PHOENIX_ENDPOINT", None)
            assert get_phoenix_endpoint() is None

    def test_collector_endpoint(self):
        """Should return PHOENIX_COLLECTOR_ENDPOINT when set."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(
            os.environ, {"PHOENIX_COLLECTOR_ENDPOINT": "https://app.phoenix.arize.com"}
        ):
            assert get_phoenix_endpoint() == "https://app.phoenix.arize.com"

    def test_legacy_endpoint_fallback(self):
        """Should fall back to PHOENIX_ENDPOINT for backward compatibility."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHOENIX_COLLECTOR_ENDPOINT", None)
            os.environ["PHOENIX_ENDPOINT"] = "http://phoenix.example.com:8080"
            assert get_phoenix_endpoint() == "http://phoenix.example.com:8080"

    def test_collector_endpoint_takes_precedence(self):
        """PHOENIX_COLLECTOR_ENDPOINT should take precedence over PHOENIX_ENDPOINT."""
        from gedcom_server.telemetry import get_phoenix_endpoint

        with patch.dict(
            os.environ,
            {
                "PHOENIX_COLLECTOR_ENDPOINT": "https://app.phoenix.arize.com",
                "PHOENIX_ENDPOINT": "http://localhost:6006",
            },
        ):
            assert get_phoenix_endpoint() == "https://app.phoenix.arize.com"


class TestUseArize:
    """Tests for _use_arize function."""

    def test_returns_false_when_no_credentials(self):
        """Should return False when Arize credentials are not set."""
        from gedcom_server.telemetry import _use_arize

        with patch.dict(os.environ, {}, clear=True):
            assert _use_arize() is False

    def test_returns_false_when_only_space_id(self):
        """Should return False when only ARIZE_SPACE_ID is set."""
        from gedcom_server.telemetry import _use_arize

        with patch.dict(os.environ, {"ARIZE_SPACE_ID": "test-space"}, clear=True):
            assert _use_arize() is False

    def test_returns_false_when_only_api_key(self):
        """Should return False when only ARIZE_API_KEY is set."""
        from gedcom_server.telemetry import _use_arize

        with patch.dict(os.environ, {"ARIZE_API_KEY": "ak-test"}, clear=True):
            assert _use_arize() is False

    def test_returns_true_when_both_set(self):
        """Should return True when both credentials are set."""
        from gedcom_server.telemetry import _use_arize

        with patch.dict(
            os.environ,
            {
                "ARIZE_SPACE_ID": "test-space",
                "ARIZE_API_KEY": "ak-test",
            },
            clear=True,
        ):
            assert _use_arize() is True


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

    @patch("dotenv.load_dotenv")
    @patch("phoenix.otel.register")
    def test_initializes_with_phoenix_register(self, mock_register, _mock_dotenv):
        """Should call phoenix.otel.register for local Phoenix."""
        import gedcom_server.telemetry as telemetry_module

        telemetry_module._tracer_provider = None
        mock_provider = MagicMock()
        mock_register.return_value = mock_provider

        with patch.dict(os.environ, {"PHOENIX_ENABLED": "true"}, clear=True):
            result = telemetry_module.initialize_tracing()

            assert result is not None
            mock_register.assert_called_once_with(
                project_name="gedcom-server",
                endpoint=None,
                batch=True,
                verbose=False,
            )

        telemetry_module._tracer_provider = None

    @patch("dotenv.load_dotenv")
    @patch("arize.otel.register")
    def test_initializes_with_arize_register(self, mock_register, _mock_dotenv):
        """Should call arize.otel.register when Arize credentials are set."""
        import gedcom_server.telemetry as telemetry_module

        telemetry_module._tracer_provider = None
        mock_provider = MagicMock()
        mock_register.return_value = mock_provider

        env = {
            "PHOENIX_ENABLED": "true",
            "ARIZE_SPACE_ID": "test-space-id",
            "ARIZE_API_KEY": "ak-test-key-123",
        }
        with patch.dict(os.environ, env, clear=True):
            result = telemetry_module.initialize_tracing()

            assert result is not None
            mock_register.assert_called_once_with(
                space_id="test-space-id",
                api_key="ak-test-key-123",
                project_name="gedcom-server",
                batch=True,
                verbose=False,
            )

        telemetry_module._tracer_provider = None

    @patch("dotenv.load_dotenv")
    @patch("phoenix.otel.register")
    def test_sets_otel_endpoint_if_not_set(self, mock_register, _mock_dotenv):
        """Should set OTEL_EXPORTER_OTLP_ENDPOINT if not already set."""
        import gedcom_server.telemetry as telemetry_module

        telemetry_module._tracer_provider = None
        mock_register.return_value = MagicMock()

        env = {
            "PHOENIX_ENABLED": "true",
            "PHOENIX_COLLECTOR_ENDPOINT": "http://custom:9999",
        }

        with patch.dict(os.environ, env, clear=True):
            telemetry_module.initialize_tracing()
            assert os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") == "http://custom:9999"

        telemetry_module._tracer_provider = None


def test_traced_tool_preserves_tool_kind_and_records_errors(monkeypatch):
    """Real spans retain TOOL classification and exception status through the processor."""
    import pytest
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from gedcom_server import telemetry

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(telemetry.StrandsToOpenInferenceProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "get_tracer", lambda: provider.get_tracer("test"))

    @telemetry.traced_tool
    def lookup(*, fail=False):
        if fail:
            raise ValueError("test failure")
        return {"found": True}

    try:
        assert lookup() == {"found": True}
        with pytest.raises(ValueError, match="test failure"):
            lookup(fail=True)
        success, failure = exporter.get_finished_spans()
        assert success.attributes[telemetry.OPENINFERENCE_SPAN_KIND] == "TOOL"
        assert failure.attributes[telemetry.OPENINFERENCE_SPAN_KIND] == "TOOL"
        assert failure.status.status_code.name == "ERROR"
        assert failure.attributes["error.type"] == "ValueError"
    finally:
        provider.shutdown()
