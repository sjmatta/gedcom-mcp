"""Tests for source-related functionality."""

from gedcom_server.models import Source
from gedcom_server.sources import _get_source, _get_sources, _search_sources
from gedcom_server.state import sources


class TestSourceDataclass:
    """Tests for the Source dataclass."""

    def test_source_to_dict(self):
        """Should include all fields in dict output."""
        source = Source(
            id="@S1@",
            title="Birth Certificate",
            author="State of New York",
            publication="Vital Records",
            repository_id="@R1@",
            note="Original document",
        )
        d = source.to_dict()
        assert d["id"] == "@S1@"
        assert d["title"] == "Birth Certificate"
        assert d["author"] == "State of New York"
        assert d["publication"] == "Vital Records"
        assert d["repository_id"] == "@R1@"
        assert d["note"] == "Original document"

    def test_source_to_summary(self):
        """Should include summary fields."""
        source = Source(
            id="@S1@",
            title="Birth Certificate",
            author="State of New York",
        )
        s = source.to_summary()
        assert s["id"] == "@S1@"
        assert s["title"] == "Birth Certificate"
        assert s["author"] == "State of New York"

    def test_source_defaults(self):
        """Should have sensible defaults."""
        source = Source(id="@S1@")
        assert source.title is None
        assert source.author is None
        assert source.publication is None
        assert source.repository_id is None
        assert source.note is None


class TestSourcesLoaded:
    """Tests that verify sources loaded correctly."""

    def test_sources_loaded(self):
        """Should load sources from GEDCOM file."""
        assert len(sources) > 0

    def test_sources_have_ids(self):
        """All sources should have IDs."""
        for source in sources.values():
            assert source.id is not None
            assert source.id.startswith("@")


class TestGetSources:
    """Tests for the get_sources function."""

    def test_get_sources_returns_list(self):
        """Should return a list."""
        result = _get_sources()
        assert isinstance(result, list)

    def test_get_sources_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _get_sources(max_results=5)
        assert len(result) <= 5

    def test_get_sources_result_has_fields(self):
        """Results should have summary fields."""
        result = _get_sources(max_results=1)
        if result:
            assert "id" in result[0]
            assert "title" in result[0]
            assert "author" in result[0]


class TestGetSource:
    """Tests for the get_source function."""

    def test_get_existing_source(self):
        """Should get an existing source."""
        source_id = next(iter(sources.keys()))
        result = _get_source(source_id)
        assert result is not None
        assert result["id"] == source_id

    def test_get_nonexistent_source(self):
        """Should return None for nonexistent source."""
        result = _get_source("NONEXISTENT999")
        assert result is None

    def test_handles_at_symbols(self):
        """Should handle IDs with @ symbols."""
        source_id = next(iter(sources.keys()))
        result = _get_source(f"@{source_id}@")
        assert result is not None


class TestSearchSources:
    """Tests for the search_sources function."""

    def test_search_returns_list(self):
        """Should return a list."""
        result = _search_sources("a")
        assert isinstance(result, list)

    def test_search_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _search_sources("a", max_results=3)
        assert len(result) <= 3

    def test_search_is_case_insensitive(self):
        """Search should be case-insensitive."""
        # Get a source with a title
        for source in sources.values():
            if source.title:
                word = source.title.split()[0]
                upper_results = _search_sources(word.upper())
                lower_results = _search_sources(word.lower())
                assert len(upper_results) == len(lower_results)
                break


class TestSourceResource:
    """Tests for source-related MCP resources.

    Note: MCP resources are decorated and return FunctionResource objects,
    so we test the underlying _get_source function instead.
    """

    def test_get_source_for_existing(self):
        """Should return source dict for existing source."""
        source_id = next(iter(sources.keys()))
        result = _get_source(source_id)
        assert result is not None
        assert "id" in result

    def test_get_source_for_nonexistent(self):
        """Should return None for missing source."""
        result = _get_source("NONEXISTENT999")
        assert result is None

    def test_get_sources_list(self):
        """Should return list of sources."""
        result = _get_sources(max_results=1000)
        assert isinstance(result, list)
        # Should have sources if there are any
        if sources:
            assert len(result) > 0
