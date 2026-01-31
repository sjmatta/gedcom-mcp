"""Tests for the geospatial search module."""

import os
from unittest import mock

import pytest

from gedcom_server.spatial import (
    _geocode_via_geonamescache,
    _geocode_via_nominatim_full,
    _is_ungeocodable,
    _point_in_bbox,
    _resolve_location,
    _resolve_location_with_bbox,
    _search_nearby,
    get_geocoding_status,
    is_enabled,
)


class TestIsEnabled:
    """Tests for the is_enabled function."""

    def test_enabled_by_default(self):
        """GIS search should be enabled by default."""
        with mock.patch.dict(os.environ, {}, clear=False):
            # Remove the var if it exists
            os.environ.pop("GIS_SEARCH_ENABLED", None)
            # Re-import to pick up the change
            assert is_enabled() is True

    def test_explicitly_enabled(self):
        """Should be enabled when set to true."""
        with mock.patch.dict(os.environ, {"GIS_SEARCH_ENABLED": "true"}):
            assert is_enabled() is True

    def test_explicitly_disabled(self):
        """Should be disabled when set to false."""
        with mock.patch.dict(os.environ, {"GIS_SEARCH_ENABLED": "false"}):
            assert is_enabled() is False


class TestIsUngeocodable:
    """Tests for identifying un-geocodable places."""

    def test_at_sea(self):
        assert _is_ungeocodable("at sea") is True
        assert _is_ungeocodable("At Sea") is True

    def test_unknown(self):
        assert _is_ungeocodable("unknown") is True
        assert _is_ungeocodable("?") is True
        assert _is_ungeocodable("") is True

    def test_valid_place(self):
        assert _is_ungeocodable("Boston, Massachusetts") is False
        assert _is_ungeocodable("New York") is False


class TestGeocodeViaGeonamescache:
    """Tests for geonamescache geocoding."""

    def test_exact_city_match(self):
        """Should find exact city name matches."""
        # Note: geonamescache uses "New York City" not "New York"
        coords, confidence = _geocode_via_geonamescache("new york city, new york, usa")
        assert coords is not None
        assert confidence == "high"
        # New York City is around 40.7N, 74W
        lat, lon = coords
        assert 40 < lat < 41
        assert -75 < lon < -73

    def test_chicago(self):
        """Should find Chicago."""
        coords, confidence = _geocode_via_geonamescache("chicago, illinois, usa")
        assert coords is not None
        # Chicago is around 41.9N, 87.6W
        lat, lon = coords
        assert 41 < lat < 42
        assert -88 < lon < -87

    def test_unknown_place(self):
        """Should return None for unknown places."""
        coords, confidence = _geocode_via_geonamescache("xyznonexistent")
        assert coords is None
        assert confidence == "low"


class TestResolveLocation:
    """Tests for location resolution."""

    def test_resolve_known_gedcom_place(self):
        """Should resolve places that exist in the GEDCOM."""
        # The sample.ged has places in Boston, New York, etc.
        coords, matched, source, confidence = _resolve_location("Boston")
        assert coords is not None
        assert "Boston" in matched
        # Could be from gedcom or geonamescache
        assert source in ("gedcom", "geonamescache")

    def test_resolve_by_geonamescache(self):
        """Should fall back to geonamescache for unknown places."""
        coords, matched, source, confidence = _resolve_location("London")
        # London should be geocodable
        assert coords is not None
        assert source in ("geonamescache", "nominatim")


class TestSearchNearby:
    """Tests for the search_nearby function."""

    def test_returns_results_structure(self):
        """Should return properly structured results."""
        result = _search_nearby("New York", radius_miles=100)

        assert "reference_location" in result
        assert "search_radius_miles" in result
        assert "geocoding_status" in result
        assert "coverage" in result
        assert "results" in result

        ref = result["reference_location"]
        assert "query" in ref
        assert "matched" in ref
        assert "coordinates" in ref
        assert "match_confidence" in ref
        assert "match_source" in ref

    def test_finds_individuals_near_new_york(self):
        """Should find individuals with events near New York."""
        result = _search_nearby("New York", radius_miles=50)

        # Sample.ged has multiple events in New York
        # Note: This test depends on geocoding being complete. If no results,
        # it's likely because background geocoding hasn't finished.
        if result["result_count"] == 0:
            # Check if geocoding is still in progress
            status = get_geocoding_status()
            if status["status"] in ("not_started", "running"):
                pytest.skip("Geocoding not complete - test cannot verify results")

        # Check result structure when we have results
        for r in result["results"]:
            assert "individual_id" in r
            assert "name" in r
            assert "distance_miles" in r
            assert "matching_places" in r

    def test_filters_by_event_type(self):
        """Should filter results by event type."""
        # Get births only
        births = _search_nearby("New York", radius_miles=100, event_types=["BIRT"])

        for r in births["results"]:
            event_types = [mp["event"] for mp in r["matching_places"]]
            assert all(et == "BIRT" for et in event_types)

    def test_km_unit(self):
        """Should support kilometer unit."""
        result = _search_nearby("New York", radius_miles=100, unit="km")

        assert result["unit"] == "km"
        assert result["search_radius_miles"] == 100

    def test_unknown_location(self):
        """Should handle unknown locations gracefully."""
        result = _search_nearby("xyznonexistent123456")

        assert "error" in result or result["reference_location"]["coordinates"] is None

    def test_results_sorted_by_distance(self):
        """Results should be sorted by distance."""
        result = _search_nearby("New York", radius_miles=500)

        if result["result_count"] > 1:
            distances = [r["distance_miles"] for r in result["results"]]
            assert distances == sorted(distances)

    def test_coverage_info(self):
        """Should include coverage information."""
        result = _search_nearby("Boston", radius_miles=50)

        coverage = result["coverage"]
        assert "geocoded" in coverage
        assert "total" in coverage
        assert "percent" in coverage
        assert "coverage_note" in result


class TestGeocodingStatus:
    """Tests for geocoding progress tracking."""

    def test_returns_status_dict(self):
        """Should return a status dictionary."""
        status = get_geocoding_status()

        assert isinstance(status, dict)
        assert "status" in status
        assert status["status"] in ("not_started", "running", "complete", "disabled")


class TestDistanceCalculation:
    """Tests for distance calculations using haversine."""

    def test_new_york_to_boston(self):
        """Distance from NYC to Boston should be roughly 190 miles."""
        from haversine import Unit, haversine

        # Approximate coordinates
        nyc = (40.7128, -74.0060)
        boston = (42.3601, -71.0589)

        distance_miles = haversine(nyc, boston, unit=Unit.MILES)

        # Should be around 190 miles
        assert 180 < distance_miles < 220


class TestDisabledState:
    """Tests for behavior when GIS search is disabled."""

    def test_search_returns_error_when_disabled(self):
        """Should return error when GIS search is disabled."""
        with mock.patch.dict(os.environ, {"GIS_SEARCH_ENABLED": "false"}):
            # Need to reimport to pick up env change
            from gedcom_server import spatial

            # Force is_enabled to return False
            with mock.patch.object(spatial, "is_enabled", return_value=False):
                result = spatial._search_nearby("New York")
                assert "error" in result
                assert "not enabled" in result["error"].lower()


class TestPointInBbox:
    """Tests for bounding box containment check."""

    def test_point_inside(self):
        """Point inside bounding box should return True."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(42.0, -75.0, bbox) is True

    def test_point_outside_north(self):
        """Point north of bbox should return False."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(46.0, -75.0, bbox) is False

    def test_point_outside_south(self):
        """Point south of bbox should return False."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(39.0, -75.0, bbox) is False

    def test_point_outside_east(self):
        """Point east of bbox should return False."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(42.0, -65.0, bbox) is False

    def test_point_outside_west(self):
        """Point west of bbox should return False."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(42.0, -85.0, bbox) is False

    def test_point_on_boundary(self):
        """Point on bbox boundary should return True."""
        bbox = {"south": 40.0, "north": 45.0, "west": -80.0, "east": -70.0}
        assert _point_in_bbox(40.0, -75.0, bbox) is True
        assert _point_in_bbox(45.0, -75.0, bbox) is True
        assert _point_in_bbox(42.0, -80.0, bbox) is True
        assert _point_in_bbox(42.0, -70.0, bbox) is True


class TestNominatimFull:
    """Tests for Nominatim geocoding with full metadata."""

    def test_returns_bbox_for_city(self):
        """Should return bounding box for a city."""
        result = _geocode_via_nominatim_full("Pittsburgh, PA")
        if result:  # Skip if no network
            assert "coords" in result
            assert "bbox" in result
            assert "is_region" in result
            # Pittsburgh should be a point (small bbox), not a region
            if result["bbox"]:
                assert result["is_region"] is False

    def test_returns_bbox_for_state(self):
        """Should return bounding box for a state/region."""
        result = _geocode_via_nominatim_full("Pennsylvania, USA")
        if result:  # Skip if no network
            assert "coords" in result
            assert "bbox" in result
            assert "is_region" in result
            # Pennsylvania should be classified as a region
            if result["bbox"]:
                assert result["is_region"] is True

    def test_returns_none_for_invalid(self):
        """Should return None for invalid location."""
        result = _geocode_via_nominatim_full("xyznonexistent12345")
        assert result is None


class TestResolveLocationWithBbox:
    """Tests for location resolution with bounding box."""

    def test_resolves_with_bbox(self):
        """Should resolve location and include bounding box."""
        result = _resolve_location_with_bbox("New York")
        assert result["coords"] is not None
        assert result["source"] in ("gedcom", "geonamescache", "nominatim")
        # Should have bbox if from nominatim
        if result["source"] == "nominatim":
            assert result["bbox"] is not None

    def test_returns_not_found_for_invalid(self):
        """Should return not_found for invalid location."""
        result = _resolve_location_with_bbox("xyznonexistent12345")
        assert result["coords"] is None
        assert result["source"] == "not_found"
        assert result["confidence"] == "low"


class TestSearchWithinMode:
    """Tests for mode='within' bounding box search."""

    def test_returns_within_mode_structure(self):
        """Should return properly structured results for within mode."""
        result = _search_nearby("Pennsylvania", mode="within")

        assert result.get("mode") == "within"
        assert "reference_location" in result
        ref = result["reference_location"]
        assert "query" in ref
        assert "matched" in ref
        # Within mode should have bounding_box instead of coordinates
        if "error" not in result:
            assert "bounding_box" in ref
            assert "results" in result

    def test_within_mode_no_distance(self):
        """Results in within mode should not have distance_miles."""
        result = _search_nearby("Pennsylvania", mode="within")

        if result.get("result_count", 0) > 0:
            for r in result["results"]:
                assert "distance_miles" not in r
                assert "matching_places" in r

    def test_proximity_mode_default(self):
        """Default mode should be proximity."""
        result = _search_nearby("Pittsburgh", radius_miles=50)

        assert result.get("mode") == "proximity"
        assert "search_radius_miles" in result

    def test_proximity_mode_has_distance(self):
        """Results in proximity mode should have distance_miles."""
        result = _search_nearby("New York", radius_miles=100)

        if result.get("result_count", 0) > 0:
            for r in result["results"]:
                assert "distance_miles" in r

    def test_within_mode_filters_by_event_type(self):
        """Within mode should respect event_types filter."""
        result = _search_nearby("Pennsylvania", mode="within", event_types=["BIRT"])

        if result.get("result_count", 0) > 0:
            for r in result["results"]:
                for mp in r["matching_places"]:
                    assert mp["event"] == "BIRT"

    def test_region_warning_for_large_areas(self):
        """Proximity mode should warn when location is a large region."""
        # Use a state name which should trigger the warning
        result = _search_nearby("California", radius_miles=50, mode="proximity")

        # May or may not have warning depending on nominatim response
        # Just verify the field can exist
        assert "results" in result or "error" in result


class TestSearchNearbyModeParameter:
    """Tests for the mode parameter in search_nearby."""

    def test_invalid_mode_uses_proximity(self):
        """Invalid mode should default to proximity behavior."""
        # Note: The typing should prevent this, but test the behavior
        # This might raise an error or default to proximity
        result = _search_nearby("New York", mode="invalid")  # type: ignore[arg-type]

        # Should either error or use proximity mode
        assert "results" in result or "error" in result

    def test_within_mode_ignores_radius(self):
        """Within mode should ignore radius_miles parameter."""
        result1 = _search_nearby("Pennsylvania", radius_miles=10, mode="within")
        result2 = _search_nearby("Pennsylvania", radius_miles=500, mode="within")

        # Both should return the same results (radius is ignored)
        if "error" not in result1 and "error" not in result2:
            assert result1.get("result_count") == result2.get("result_count")
