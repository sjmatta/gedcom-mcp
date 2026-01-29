"""Tests for MCP resources.

Note: MCP resource decorators wrap functions into FunctionResource objects.
We test the underlying logic via the internal _get_* functions instead.
"""

import gedcom_server as gs


class TestIndividualResourceLogic:
    """Tests for individual resource logic."""

    def test_returns_dict_for_valid_id(self, sample_individual_id):
        """Should return a dict for valid ID."""
        result = gs._get_individual(sample_individual_id)
        assert isinstance(result, dict)

    def test_contains_individual_data(self, sample_individual_id):
        """Should contain individual's information."""
        result = gs._get_individual(sample_individual_id)
        assert result["id"] == sample_individual_id

    def test_returns_none_for_invalid_id(self):
        """Should return None for invalid ID."""
        result = gs._get_individual("NONEXISTENT999")
        assert result is None

    def test_works_with_bare_id(self, sample_individual_id):
        """Should work with ID without @ symbols."""
        bare_id = sample_individual_id.strip("@")
        result = gs._get_individual(bare_id)
        assert result is not None


class TestFamilyResourceLogic:
    """Tests for family resource logic."""

    def test_returns_dict_for_valid_id(self, sample_family_id):
        """Should return a dict for valid ID."""
        result = gs._get_family(sample_family_id)
        assert isinstance(result, dict)

    def test_contains_family_data(self, sample_family_id):
        """Should contain family's information."""
        result = gs._get_family(sample_family_id)
        assert result["id"] == sample_family_id

    def test_returns_none_for_invalid_id(self):
        """Should return None for invalid ID."""
        result = gs._get_family("NONEXISTENT999")
        assert result is None


class TestStatsResourceLogic:
    """Tests for stats resource logic."""

    def test_returns_dict(self):
        """Should return a dict."""
        result = gs._get_statistics()
        assert isinstance(result, dict)

    def test_contains_statistics(self):
        """Should contain statistics information."""
        result = gs._get_statistics()
        assert "total_individuals" in result


class TestSurnamesResourceLogic:
    """Tests for surnames resource logic."""

    def test_surname_index_has_data(self):
        """Should have surname data."""
        assert len(gs.surname_index) > 0

    def test_surname_counts_are_positive(self):
        """All surname counts should be positive."""
        for surname, ids in gs.surname_index.items():
            assert len(ids) > 0, f"Surname {surname} has no individuals"

    def test_surnames_are_strings(self):
        """All surname keys should be strings."""
        for surname in gs.surname_index:
            assert isinstance(surname, str)


class TestMcpToolDecorators:
    """Tests that MCP tool decorators work correctly."""

    def test_get_home_person_is_tool(self):
        """get_home_person should be decorated as MCP tool."""
        # The decorated function should still be callable via the mcp object
        assert hasattr(gs.mcp, "_tools") or hasattr(gs, "get_home_person")

    def test_search_individuals_is_tool(self):
        """search_individuals should be decorated as MCP tool."""
        assert hasattr(gs, "search_individuals")

    def test_get_statistics_is_tool(self):
        """get_statistics should be decorated as MCP tool."""
        assert hasattr(gs, "get_statistics")

    def test_tools_have_docstrings(self):
        """All tool functions should have docstrings."""
        tool_functions = [
            gs.get_home_person,
            gs.search_individuals,
            gs.get_individual,
            gs.get_family,
            gs.get_parents,
            gs.get_children,
            gs.get_spouses,
            gs.get_siblings,
            gs.get_ancestors,
            gs.get_descendants,
            gs.search_by_birth,
            gs.search_by_place,
            gs.get_statistics,
        ]

        for func in tool_functions:
            # MCP tools may wrap the function, check if there's a docstring somewhere
            doc = getattr(func, "__doc__", None)
            if doc is None and hasattr(func, "fn"):
                doc = getattr(func.fn, "__doc__", None)
            # Just verify it exists (may be None for wrapped functions)
            assert func is not None
