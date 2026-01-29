"""Tests for MCP resources.

Note: MCP resource decorators wrap functions into FunctionResource objects.
We test the underlying logic via the internal _get_* functions instead.
"""

from gedcom_server import mcp
from gedcom_server.core import _get_family, _get_individual, _get_statistics
from gedcom_server.state import surname_index


class TestIndividualResourceLogic:
    """Tests for individual resource logic."""

    def test_returns_dict_for_valid_id(self, sample_individual_id):
        """Should return a dict for valid ID."""
        result = _get_individual(sample_individual_id)
        assert isinstance(result, dict)

    def test_contains_individual_data(self, sample_individual_id):
        """Should contain individual's information."""
        result = _get_individual(sample_individual_id)
        assert result["id"] == sample_individual_id

    def test_returns_none_for_invalid_id(self):
        """Should return None for invalid ID."""
        result = _get_individual("NONEXISTENT999")
        assert result is None

    def test_works_with_bare_id(self, sample_individual_id):
        """Should work with ID without @ symbols."""
        bare_id = sample_individual_id.strip("@")
        result = _get_individual(bare_id)
        assert result is not None


class TestFamilyResourceLogic:
    """Tests for family resource logic."""

    def test_returns_dict_for_valid_id(self, sample_family_id):
        """Should return a dict for valid ID."""
        result = _get_family(sample_family_id)
        assert isinstance(result, dict)

    def test_contains_family_data(self, sample_family_id):
        """Should contain family's information."""
        result = _get_family(sample_family_id)
        assert result["id"] == sample_family_id

    def test_returns_none_for_invalid_id(self):
        """Should return None for invalid ID."""
        result = _get_family("NONEXISTENT999")
        assert result is None


class TestStatsResourceLogic:
    """Tests for stats resource logic."""

    def test_returns_dict(self):
        """Should return a dict."""
        result = _get_statistics()
        assert isinstance(result, dict)

    def test_contains_statistics(self):
        """Should contain statistics information."""
        result = _get_statistics()
        assert "total_individuals" in result


class TestSurnamesResourceLogic:
    """Tests for surnames resource logic."""

    def test_surname_index_has_data(self):
        """Should have surname data."""
        assert len(surname_index) > 0

    def test_surname_counts_are_positive(self):
        """All surname counts should be positive."""
        for surname, ids in surname_index.items():
            assert len(ids) > 0, f"Surname {surname} has no individuals"

    def test_surnames_are_strings(self):
        """All surname keys should be strings."""
        for surname in surname_index:
            assert isinstance(surname, str)


class TestMcpToolDecorators:
    """Tests that MCP tool decorators work correctly."""

    def test_mcp_instance_exists(self):
        """MCP instance should exist."""
        assert mcp is not None

    def test_mcp_has_tools(self):
        """MCP should have tools registered."""
        tools = mcp._tool_manager._tools
        assert len(tools) > 0

    def test_get_home_person_is_tool(self):
        """get_home_person should be decorated as MCP tool."""
        tools = mcp._tool_manager._tools
        assert "get_home_person" in tools

    def test_search_individuals_is_tool(self):
        """search_individuals should be decorated as MCP tool."""
        tools = mcp._tool_manager._tools
        assert "search_individuals" in tools

    def test_get_statistics_is_tool(self):
        """get_statistics should be decorated as MCP tool."""
        tools = mcp._tool_manager._tools
        assert "get_statistics" in tools

    def test_all_expected_tools_registered(self):
        """All expected tools should be registered."""
        tools = set(mcp._tool_manager._tools.keys())
        expected_tools = {
            "get_home_person",
            "search_individuals",
            "get_individual",
            "get_family",
            "get_parents",
            "get_children",
            "get_spouses",
            "get_siblings",
            "get_ancestors",
            "get_descendants",
            "search_by_birth",
            "search_by_place",
            "fuzzy_search_place",
            "search_similar_places",
            "get_place_variants",
            "get_all_places",
            "get_place",
            "geocode_place",
            "search_nearby",
            "get_statistics",
            "get_sources",
            "get_source",
            "search_sources",
            "get_events",
            "search_events",
            "get_citations",
            "get_notes",
            "get_timeline",
            "get_biography",
            "search_narrative",
            "get_repositories",
        }
        missing = expected_tools - tools
        assert not missing, f"Missing tools: {missing}"
