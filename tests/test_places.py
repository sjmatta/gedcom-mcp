"""Tests for place-related functionality including fuzzy search and geocoding."""

from gedcom_server import mcp
from gedcom_server.constants import HISTORICAL_MAPPINGS, HISTORICAL_NAMES
from gedcom_server.helpers import get_place_id, normalize_place_string, parse_place_components
from gedcom_server.models import Place
from gedcom_server.places import (
    _fuzzy_match_places,
    _fuzzy_search_place,
    _geocode_place,
    _get_all_places,
    _get_historical_variants,
    _get_place,
    _get_place_variants,
    _phonetic_match_places,
    _search_nearby,
    _search_similar_places,
)
from gedcom_server.state import individual_places, places


class TestPlaceDataclass:
    """Tests for the Place dataclass."""

    def test_place_to_dict(self):
        """Should include all fields in dict output."""
        place = Place(
            id="abc123",
            original="New York, USA",
            normalized="new york, united states",
            components=["New York", "USA"],
            latitude=40.7128,
            longitude=-74.0060,
        )
        d = place.to_dict()
        assert d["id"] == "abc123"
        assert d["original"] == "New York, USA"
        assert d["normalized"] == "new york, united states"
        assert d["components"] == ["New York", "USA"]
        assert d["latitude"] == 40.7128
        assert d["longitude"] == -74.0060

    def test_place_to_summary(self):
        """Should include summary fields."""
        place = Place(
            id="abc123",
            original="New York, USA",
            normalized="new york, united states",
        )
        s = place.to_summary()
        assert s["id"] == "abc123"
        assert s["original"] == "New York, USA"
        assert s["normalized"] == "new york, united states"

    def test_place_defaults(self):
        """Should have sensible defaults."""
        place = Place(id="abc123", original="Test", normalized="test")
        assert place.components == []
        assert place.latitude is None
        assert place.longitude is None


class TestPlacesLoaded:
    """Tests that verify places loaded correctly."""

    def test_places_loaded(self):
        """Should load places from GEDCOM file."""
        assert len(places) > 0

    def test_places_have_ids(self):
        """All places should have IDs."""
        for place in places.values():
            assert place.id is not None
            assert len(place.id) > 0

    def test_places_have_normalized_form(self):
        """All places should have normalized form."""
        for place in places.values():
            assert place.normalized is not None
            assert place.normalized == place.normalized.lower()

    def test_individual_places_indexed(self):
        """Individuals should be linked to their places."""
        assert len(individual_places) > 0


class TestNormalization:
    """Tests for place normalization functions."""

    def test_normalize_lowercase(self):
        """Should lowercase the place string."""
        result = normalize_place_string("New York City")
        assert result == result.lower()

    def test_normalize_expands_abbreviations(self):
        """Should expand common abbreviations."""
        assert "saint" in normalize_place_string("St. Louis")
        assert "county" in normalize_place_string("Wayne Co.")
        assert "mount" in normalize_place_string("Mt. Vernon")
        assert "fort" in normalize_place_string("Ft. Worth")

    def test_normalize_collapses_whitespace(self):
        """Should collapse multiple spaces to single space."""
        result = normalize_place_string("New   York    City")
        assert "  " not in result

    def test_normalize_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        result = normalize_place_string("  New York  ")
        assert result == "new york"

    def test_parse_place_components(self):
        """Should split place by commas."""
        components = parse_place_components("New York, New York, USA")
        assert len(components) == 3
        assert components[0] == "New York"
        assert components[1] == "New York"
        assert components[2] == "USA"

    def test_get_place_id_consistent(self):
        """Same place should get same ID."""
        id1 = get_place_id("New York, USA")
        id2 = get_place_id("New York, USA")
        assert id1 == id2

    def test_get_place_id_normalized(self):
        """Similar places should get same ID after normalization."""
        id1 = get_place_id("St. Louis, MO")
        id2 = get_place_id("st. louis, mo")
        assert id1 == id2


class TestHistoricalMappings:
    """Tests for historical place name mappings."""

    def test_historical_names_defined(self):
        """Should have historical name mappings."""
        assert len(HISTORICAL_NAMES) > 0

    def test_historical_mappings_bidirectional(self):
        """Should have bidirectional mappings."""
        # Check that modern names map back to historical
        assert "istanbul" in HISTORICAL_MAPPINGS
        assert "constantinople" in HISTORICAL_MAPPINGS["istanbul"]

    def test_get_historical_variants(self):
        """Should return variants for historical places."""
        variants = _get_historical_variants("Constantinople")
        assert len(variants) > 0


class TestFuzzyMatchPlaces:
    """Tests for fuzzy place matching."""

    def test_fuzzy_match_returns_list(self):
        """Should return a list of tuples."""
        # Use a place that exists in the tree
        if places:
            sample_place = next(iter(places.values())).original
            first_word = sample_place.split(",")[0][:5]  # First 5 chars
            result = _fuzzy_match_places(first_word, threshold=30)
            assert isinstance(result, list)

    def test_fuzzy_match_returns_scores(self):
        """Results should include scores."""
        if places:
            sample_place = next(iter(places.values())).original
            result = _fuzzy_match_places(sample_place, threshold=30)
            if result:
                assert len(result[0]) == 2
                assert isinstance(result[0][1], float)

    def test_fuzzy_match_respects_threshold(self):
        """Should only return matches above threshold."""
        # With very high threshold, should get fewer matches
        high_threshold_results = _fuzzy_match_places("test", threshold=95)
        low_threshold_results = _fuzzy_match_places("test", threshold=30)
        assert len(high_threshold_results) <= len(low_threshold_results)


class TestPhoneticMatchPlaces:
    """Tests for phonetic place matching."""

    def test_phonetic_match_returns_list(self):
        """Should return a list of strings."""
        result = _phonetic_match_places("Vienna")
        assert isinstance(result, list)


class TestFuzzySearchPlace:
    """Tests for the fuzzy_search_place tool."""

    def test_returns_list(self):
        """Should return a list."""
        result = _fuzzy_search_place("a", threshold=30)
        assert isinstance(result, list)

    def test_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _fuzzy_search_place("a", threshold=30, max_results=5)
        assert len(result) <= 5

    def test_results_have_match_info(self):
        """Results should include match information."""
        result = _fuzzy_search_place("a", threshold=30, max_results=5)
        if result:
            assert "id" in result[0]
            assert "name" in result[0]
            assert "match_score" in result[0]

    def test_high_threshold_returns_better_matches(self):
        """Higher threshold should return higher quality matches."""
        high_results = _fuzzy_search_place("a", threshold=90, max_results=10)
        low_results = _fuzzy_search_place("a", threshold=30, max_results=10)
        # High threshold should return equal or fewer results
        assert len(high_results) <= len(low_results)


class TestSearchSimilarPlaces:
    """Tests for the search_similar_places tool."""

    def test_returns_list(self):
        """Should return a list."""
        result = _search_similar_places("New York")
        assert isinstance(result, list)

    def test_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _search_similar_places("a", max_results=3)
        assert len(result) <= 3

    def test_results_have_similarity_info(self):
        """Results should include similarity information."""
        result = _search_similar_places("a", max_results=5)
        if result:
            assert "place" in result[0]
            assert "similarity_score" in result[0]


class TestGetPlaceVariants:
    """Tests for the get_place_variants tool."""

    def test_returns_list(self):
        """Should return a list."""
        result = _get_place_variants("New York")
        assert isinstance(result, list)

    def test_variants_have_match_type(self):
        """Variants should include match type."""
        # Use a place that exists in the tree
        if places:
            sample_place = next(iter(places.values())).original
            result = _get_place_variants(sample_place)
            if result:
                assert "place" in result[0]
                assert "match_type" in result[0]


class TestGetAllPlaces:
    """Tests for the get_all_places tool."""

    def test_returns_list(self):
        """Should return a list."""
        result = _get_all_places()
        assert isinstance(result, list)

    def test_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _get_all_places(max_results=10)
        assert len(result) <= 10

    def test_results_have_summary_fields(self):
        """Results should have summary fields."""
        result = _get_all_places(max_results=5)
        if result:
            assert "id" in result[0]
            assert "original" in result[0]
            assert "normalized" in result[0]


class TestGetPlace:
    """Tests for the get_place tool."""

    def test_get_existing_place(self):
        """Should get an existing place by ID."""
        if places:
            place_id = next(iter(places.keys()))
            result = _get_place(place_id)
            assert result is not None
            assert result["id"] == place_id

    def test_get_nonexistent_place(self):
        """Should return None for nonexistent place."""
        result = _get_place("NONEXISTENT999")
        assert result is None


class TestGeocodePlace:
    """Tests for the geocode_place tool."""

    def test_returns_dict_or_none(self):
        """Should return dict or None."""
        result = _geocode_place("New York City")
        assert result is None or isinstance(result, dict)

    def test_result_has_coordinates(self):
        """If successful, result should have coordinates."""
        result = _geocode_place("New York City")
        if result:
            assert "latitude" in result
            assert "longitude" in result
            assert "source" in result


class TestSearchNearby:
    """Tests for the search_nearby tool.

    Note: These tests may be slow due to geocoding.
    """

    def test_returns_list(self):
        """Should return a list."""
        # Use a small radius to avoid triggering full geocoding
        result = _search_nearby("Nonexistent Place 12345")
        assert isinstance(result, list)
        # For a nonexistent place, should return empty list
        assert len(result) == 0

    def test_respects_max_results(self):
        """Should respect max_results parameter."""
        # Skip full geocoding by using small max_results
        result = _search_nearby("London", max_results=2, radius_km=10)
        assert len(result) <= 2

    def test_results_have_distance(self):
        """Results should include distance information."""
        # This test only runs if we get results
        result = _search_nearby("London", radius_km=100, max_results=5)
        if result:
            assert "distance_km" in result[0]


class TestMCPToolDecorators:
    """Tests that MCP tools are properly decorated.

    Note: MCP tools are registered on the mcp instance.
    We verify they are registered by checking the tool manager.
    """

    def test_fuzzy_search_place_is_tool(self):
        """fuzzy_search_place should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "fuzzy_search_place" in tools

    def test_search_similar_places_is_tool(self):
        """search_similar_places should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "search_similar_places" in tools

    def test_get_place_variants_is_tool(self):
        """get_place_variants should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "get_place_variants" in tools

    def test_get_all_places_is_tool(self):
        """get_all_places should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "get_all_places" in tools

    def test_search_nearby_is_tool(self):
        """search_nearby should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "search_nearby" in tools

    def test_geocode_place_is_tool(self):
        """geocode_place should be a registered tool."""
        tools = mcp._tool_manager._tools
        assert "geocode_place" in tools
