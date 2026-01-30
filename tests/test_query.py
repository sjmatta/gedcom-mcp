"""Tests for the natural language query tool."""

from unittest.mock import MagicMock, patch

from gedcom_server.query import (
    TOOL_DEFINITIONS,
    TOOL_FUNCTIONS,
    _execute_tool,
    _extract_text_response,
    _query,
)


class TestToolDefinitions:
    """Test that tool definitions are properly configured."""

    def test_all_tools_have_definitions(self):
        """Every tool function should have a corresponding definition."""
        defined_tools = {t["function"]["name"] for t in TOOL_DEFINITIONS}
        function_tools = set(TOOL_FUNCTIONS.keys())
        assert defined_tools == function_tools

    def test_tool_definitions_have_required_fields(self):
        """Each tool definition should have the required OpenAI format fields."""
        for tool_def in TOOL_DEFINITIONS:
            assert tool_def["type"] == "function"
            assert "function" in tool_def
            func = tool_def["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func


class TestExecuteTool:
    """Test the tool execution wrapper."""

    def test_execute_known_tool(self):
        """Known tools should execute successfully."""
        result = _execute_tool("get_statistics", {})
        assert isinstance(result, dict)
        assert "total_individuals" in result

    def test_execute_unknown_tool(self):
        """Unknown tools should return an error."""
        result = _execute_tool("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_tool_with_bad_args(self):
        """Tools with invalid arguments should return an error."""
        result = _execute_tool("get_biography", {"individual_id": None})
        # Should either work (returning None) or return an error dict
        assert result is None or isinstance(result, dict)

    def test_execute_search_individuals(self):
        """Test executing search_individuals tool."""
        result = _execute_tool("search_individuals", {"name": "Smith", "max_results": 5})
        assert isinstance(result, list)


class TestExtractTextResponse:
    """Test extracting text from LLM responses."""

    def test_extract_from_valid_response(self):
        """Should extract text from a valid response object."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"

        result = _extract_text_response(mock_response)
        assert result == "Test response"

    def test_extract_from_empty_response(self):
        """Should return empty string for empty response."""
        mock_response = MagicMock()
        mock_response.choices = []

        result = _extract_text_response(mock_response)
        assert result == ""

    def test_extract_from_none_content(self):
        """Should return empty string when content is None."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        result = _extract_text_response(mock_response)
        assert result == ""


class TestQuery:
    """Test the main query function with mocked LLM."""

    @patch("gedcom_server.query.litellm.completion")
    def test_query_simple_response(self, mock_completion):
        """Test a simple query that doesn't need tool calls."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "The family tree has 100 individuals."
        mock_response.choices[0].message.tool_calls = None
        mock_completion.return_value = mock_response

        result = _query("How many people are in the tree?")

        assert result == "The family tree has 100 individuals."
        mock_completion.assert_called_once()

    @patch("gedcom_server.query.litellm.completion")
    def test_query_with_tool_call(self, mock_completion):
        """Test a query that requires a tool call."""
        # First response: tool call
        tool_call_response = MagicMock()
        tool_call_response.choices = [MagicMock()]
        tool_call_response.choices[0].finish_reason = "tool_calls"
        tool_call_response.choices[0].message.content = ""

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_statistics"
        tool_call.function.arguments = "{}"
        tool_call_response.choices[0].message.tool_calls = [tool_call]

        # Second response: final answer
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].finish_reason = "stop"
        final_response.choices[0].message.content = "There are many people in the tree."
        final_response.choices[0].message.tool_calls = None

        mock_completion.side_effect = [tool_call_response, final_response]

        result = _query("Tell me about the tree")

        assert result == "There are many people in the tree."
        assert mock_completion.call_count == 2

    @patch("gedcom_server.query.litellm.completion")
    def test_query_handles_llm_error(self, mock_completion):
        """Test that LLM errors are handled gracefully."""
        mock_completion.side_effect = Exception("API error")

        result = _query("Test question")

        assert "Error communicating with LLM" in result

    @patch("gedcom_server.query.litellm.completion")
    def test_query_handles_empty_choices(self, mock_completion):
        """Test handling of response with no choices."""
        mock_response = MagicMock()
        mock_response.choices = []
        mock_completion.return_value = mock_response

        result = _query("Test question")

        assert result == "No response from LLM"

    @patch("gedcom_server.query.litellm.completion")
    @patch.dict("os.environ", {"GEDCOM_QUERY_MAX_ITERATIONS": "2"})
    def test_query_respects_max_iterations(self, mock_completion):
        """Test that query respects max iterations limit."""
        # Always return tool calls to force iteration limit
        tool_call_response = MagicMock()
        tool_call_response.choices = [MagicMock()]
        tool_call_response.choices[0].finish_reason = "tool_calls"
        tool_call_response.choices[0].message.content = ""

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_statistics"
        tool_call.function.arguments = "{}"
        tool_call_response.choices[0].message.tool_calls = [tool_call]

        mock_completion.return_value = tool_call_response

        result = _query("Test question")

        assert "maximum iterations" in result.lower()
        # Should have been called exactly max_iterations times
        assert mock_completion.call_count == 2

    @patch("gedcom_server.query.litellm.completion")
    def test_query_passes_correct_model(self, mock_completion):
        """Test that the correct model is passed to litellm."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None
        mock_completion.return_value = mock_response

        _query("Test")

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert "tools" in call_kwargs
        assert "system" in call_kwargs

    @patch("gedcom_server.query.litellm.completion")
    @patch.dict("os.environ", {"GEDCOM_QUERY_MODEL": "gpt-4"})
    def test_query_uses_env_model(self, mock_completion):
        """Test that GEDCOM_QUERY_MODEL env var is respected."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None
        mock_completion.return_value = mock_response

        _query("Test")

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "gpt-4"


class TestToolCallParsing:
    """Test parsing of tool call arguments."""

    @patch("gedcom_server.query.litellm.completion")
    def test_handles_malformed_json_arguments(self, mock_completion):
        """Test that malformed JSON in tool arguments is handled."""
        # First response: tool call with bad JSON
        tool_call_response = MagicMock()
        tool_call_response.choices = [MagicMock()]
        tool_call_response.choices[0].finish_reason = "tool_calls"
        tool_call_response.choices[0].message.content = ""

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_statistics"
        tool_call.function.arguments = "not valid json"
        tool_call_response.choices[0].message.tool_calls = [tool_call]

        # Second response: final answer
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].finish_reason = "stop"
        final_response.choices[0].message.content = "Done"
        final_response.choices[0].message.tool_calls = None

        mock_completion.side_effect = [tool_call_response, final_response]

        # Should not raise, should handle gracefully
        result = _query("Test")
        assert result == "Done"
