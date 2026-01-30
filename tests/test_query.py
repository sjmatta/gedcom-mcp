"""Tests for the natural language query tool using Strands Agents SDK."""

from unittest.mock import MagicMock, patch

from gedcom_server.query import (
    SYSTEM_PROMPT,
    TOOLS,
    _create_agent,
    _query,
    _query_sync,
    _query_with_callback,
)


class TestToolDefinitions:
    """Test that tools are properly configured."""

    def test_all_required_tools_present(self):
        """All required genealogy tools should be available."""
        tool_names = {t.tool_name for t in TOOLS}
        expected_tools = {
            "get_home_person",
            "get_biography",
            "get_ancestors",
            "get_descendants",
            "get_relationship",
            "get_surname_group",
            "search_individuals",
            "get_statistics",
        }
        assert tool_names == expected_tools

    def test_tools_are_callable(self):
        """Each tool should be callable."""
        for tool in TOOLS:
            assert callable(tool)


class TestSystemPrompt:
    """Test system prompt configuration."""

    def test_system_prompt_mentions_home_person(self):
        """System prompt should instruct to call get_home_person first."""
        assert "get_home_person" in SYSTEM_PROMPT
        assert "ALWAYS" in SYSTEM_PROMPT

    def test_system_prompt_has_tool_guidance(self):
        """System prompt should provide guidance for each tool."""
        for tool_name in ["get_biography", "get_ancestors", "get_descendants", "get_relationship"]:
            assert tool_name in SYSTEM_PROMPT


class TestCreateAgent:
    """Test agent creation."""

    @patch("gedcom_server.query.AnthropicModel")
    @patch("gedcom_server.query.Agent")
    def test_creates_agent_with_correct_config(self, mock_agent_class, mock_model_class):
        """Agent should be created with correct model and tools."""
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model

        _create_agent()

        mock_model_class.assert_called_once()
        mock_agent_class.assert_called_once()
        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs["model"] == mock_model
        assert call_kwargs["tools"] == TOOLS
        assert call_kwargs["system_prompt"] == SYSTEM_PROMPT

    @patch("gedcom_server.query.AnthropicModel")
    @patch("gedcom_server.query.Agent")
    def test_creates_agent_with_custom_callback(self, mock_agent_class, mock_model_class):
        """Agent should accept custom callback handler."""
        mock_callback = MagicMock()

        _create_agent(callback_handler=mock_callback)

        call_kwargs = mock_agent_class.call_args[1]
        assert call_kwargs["callback_handler"] == mock_callback

    @patch.dict("os.environ", {"GEDCOM_QUERY_MODEL": "claude-opus-4-20250514"})
    @patch("gedcom_server.query.AnthropicModel")
    @patch("gedcom_server.query.Agent")
    def test_uses_env_model(self, mock_agent_class, mock_model_class):
        """GEDCOM_QUERY_MODEL env var should be respected."""
        _create_agent()

        call_kwargs = mock_model_class.call_args[1]
        assert call_kwargs["model_id"] == "claude-opus-4-20250514"


class TestQuerySync:
    """Test the synchronous query function."""

    @patch("gedcom_server.query._create_agent")
    def test_query_sync_returns_string(self, mock_create_agent):
        """Sync query should return text from agent result."""
        # Message is a TypedDict with content as a list of ContentBlock dicts
        mock_result = MagicMock()
        mock_result.message = {
            "role": "assistant",
            "content": [{"text": "The answer is 42."}],
        }

        mock_agent = MagicMock()
        mock_agent.return_value = mock_result
        mock_create_agent.return_value = mock_agent

        result = _query_sync("What is the meaning of life?")

        assert result == "The answer is 42."
        mock_agent.assert_called_once_with("What is the meaning of life?")

    @patch("gedcom_server.query._create_agent")
    def test_query_sync_concatenates_multiple_blocks(self, mock_create_agent):
        """Sync query should concatenate multiple text blocks."""
        mock_result = MagicMock()
        mock_result.message = {
            "role": "assistant",
            "content": [{"text": "Hello "}, {"text": "world!"}],
        }

        mock_agent = MagicMock()
        mock_agent.return_value = mock_result
        mock_create_agent.return_value = mock_agent

        result = _query_sync("Test question")

        assert result == "Hello world!"

    @patch("gedcom_server.query._create_agent")
    def test_query_sync_handles_empty_message(self, mock_create_agent):
        """Sync query should handle empty message gracefully."""
        mock_result = MagicMock()
        mock_result.message = None

        mock_agent = MagicMock()
        mock_agent.return_value = mock_result
        mock_create_agent.return_value = mock_agent

        result = _query_sync("Test question")

        assert result == "Unable to generate a response."

    @patch("gedcom_server.query._create_agent")
    def test_query_sync_handles_empty_content(self, mock_create_agent):
        """Sync query should handle empty content gracefully."""
        mock_result = MagicMock()
        mock_result.message = {"role": "assistant", "content": []}

        mock_agent = MagicMock()
        mock_agent.return_value = mock_result
        mock_create_agent.return_value = mock_agent

        result = _query_sync("Test question")

        # Empty content list is treated as no response
        assert result == "Unable to generate a response."

    @patch("gedcom_server.query._create_agent")
    def test_query_sync_skips_non_text_blocks(self, mock_create_agent):
        """Sync query should skip blocks without text key."""
        # ContentBlocks can be tool_use blocks without text
        mock_result = MagicMock()
        mock_result.message = {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "123", "name": "test"}},  # No text
                {"text": "Text content"},
            ],
        }

        mock_agent = MagicMock()
        mock_agent.return_value = mock_result
        mock_create_agent.return_value = mock_agent

        result = _query_sync("Test question")

        assert result == "Text content"


class TestQueryWithCallback:
    """Test the callback-based streaming query function."""

    @patch("gedcom_server.query._create_agent")
    def test_query_with_callback_yields_chunks(self, mock_create_agent):
        """Callback query should yield chunks from callback."""

        def capture_callback_handler(callback_handler):
            # Simulate the agent calling the callback
            callback_handler(data="Hello ")
            callback_handler(data="world!")
            return MagicMock()

        mock_create_agent.side_effect = capture_callback_handler

        chunks = list(_query_with_callback("Test question"))

        assert chunks == ["Hello ", "world!"]

    @patch("gedcom_server.query._create_agent")
    def test_query_with_callback_ignores_non_data_events(self, mock_create_agent):
        """Callback query should ignore events without data."""

        def capture_callback_handler(callback_handler):
            callback_handler(complete=True)  # No 'data' key
            callback_handler(data="Content")
            callback_handler(tool_use={"name": "test"})  # No 'data' key
            return MagicMock()

        mock_create_agent.side_effect = capture_callback_handler

        chunks = list(_query_with_callback("Test question"))

        assert chunks == ["Content"]


class TestQueryAlias:
    """Test that _query is an alias for _query_sync."""

    def test_query_is_sync_alias(self):
        """_query should be the same function as _query_sync."""
        assert _query is _query_sync


class TestToolExecution:
    """Test that wrapped tools can be executed."""

    def test_get_statistics_tool_executes(self):
        """get_statistics tool should execute and return data."""
        from gedcom_server.query import get_statistics

        result = get_statistics()
        assert isinstance(result, dict)
        assert "total_individuals" in result

    def test_search_individuals_tool_executes(self):
        """search_individuals tool should execute and return list."""
        from gedcom_server.query import search_individuals

        result = search_individuals("Smith", 5)
        assert isinstance(result, list)
