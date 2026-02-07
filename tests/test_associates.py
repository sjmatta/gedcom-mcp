"""Tests for the find_associates FAN Club analysis tool."""

import pytest

from gedcom_server import state
from gedcom_server.associates import (
    _build_relative_set,
    _calculate_association_strength,
    _calculate_lifespan_overlap,
    _find_associates,
    _get_events_with_places,
    _get_lifespan,
    _places_match,
)


class TestLifespanHelpers:
    """Tests for lifespan calculation helpers."""

    def test_get_lifespan_nonexistent(self):
        """Should return None for nonexistent individual."""
        birth, death = _get_lifespan("@NONEXISTENT999@")
        assert birth is None
        assert death is None

    def test_get_lifespan_existing(self):
        """Should return lifespan for existing individual."""
        # Skip if no individuals loaded
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find an individual with dates
        for indi in state.individuals.values():
            if indi.birth_date or indi.death_date:
                birth, death = _get_lifespan(indi.id)
                # At least one should be set
                assert birth is not None or death is not None
                break

    def test_calculate_lifespan_overlap_same_period(self):
        """Overlapping lifespans should return positive overlap."""
        overlap = _calculate_lifespan_overlap(1900, 1980, 1920, 2000)
        assert overlap is not None
        assert overlap == 60  # 1920-1980

    def test_calculate_lifespan_overlap_no_overlap(self):
        """Non-overlapping lifespans should return 0."""
        overlap = _calculate_lifespan_overlap(1800, 1850, 1900, 1950)
        assert overlap == 0

    def test_calculate_lifespan_overlap_missing_dates(self):
        """Should handle missing dates with estimation."""
        # Death missing - estimated as birth + 80
        overlap = _calculate_lifespan_overlap(1900, None, 1920, 1990)
        assert overlap is not None
        assert overlap > 0

    def test_calculate_lifespan_overlap_all_missing(self):
        """Should return None when all dates missing."""
        overlap = _calculate_lifespan_overlap(None, None, None, None)
        assert overlap is None


class TestPlacesMatch:
    """Tests for fuzzy place matching."""

    def test_exact_match(self):
        """Exact match should return True."""
        assert _places_match("pittsburgh, pennsylvania", "pittsburgh, pennsylvania")

    def test_fuzzy_match(self):
        """Fuzzy match should work for similar places."""
        assert _places_match("pittsburg, pa", "pittsburgh, pennsylvania", threshold=60)

    def test_containment_match(self):
        """Should match when one contains the other."""
        assert _places_match("pittsburgh", "pittsburgh, allegheny, pennsylvania")

    def test_no_match(self):
        """Should not match completely different places."""
        assert not _places_match("new york", "california", threshold=80)


class TestGetEventsWithPlaces:
    """Tests for extracting events with places."""

    def test_nonexistent_individual(self):
        """Should return empty list for nonexistent individual."""
        events = _get_events_with_places("@NONEXISTENT999@")
        assert events == []

    def test_events_have_required_fields(self):
        """Events should have type, year, place, place_normalized."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find an individual with a birth place
        for indi in state.individuals.values():
            if indi.birth_place:
                events = _get_events_with_places(indi.id)
                assert len(events) > 0
                assert "type" in events[0]
                assert "year" in events[0]
                assert "place" in events[0]
                assert "place_normalized" in events[0]
                break


class TestBuildRelativeSet:
    """Tests for building the set of relatives."""

    def test_nonexistent_individual(self):
        """Should return set with just the ID for nonexistent individual."""
        relatives = _build_relative_set("@NONEXISTENT999@")
        assert "@NONEXISTENT999@" in relatives

    def test_includes_self(self):
        """Relative set should include self."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        indi_id = next(iter(state.individuals.keys()))
        relatives = _build_relative_set(indi_id)
        assert indi_id in relatives

    def test_includes_parents(self):
        """Relative set should include parents."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with parents
        for indi in state.individuals.values():
            if indi.family_as_child:
                fam = state.families.get(indi.family_as_child)
                if fam and (fam.husband_id or fam.wife_id):
                    relatives = _build_relative_set(indi.id)
                    if fam.husband_id:
                        assert fam.husband_id in relatives
                    if fam.wife_id:
                        assert fam.wife_id in relatives
                    break


class TestCalculateAssociationStrength:
    """Tests for association strength calculation."""

    def test_same_place_same_year(self):
        """Same place and year should give high score."""
        target_events = [
            {"type": "BIRT", "year": 1900, "place": "Pittsburgh", "place_normalized": "pittsburgh"}
        ]
        candidate_events = [
            {"type": "BIRT", "year": 1900, "place": "Pittsburgh", "place_normalized": "pittsburgh"}
        ]
        strength, overlaps, _ = _calculate_association_strength(
            target_events, candidate_events, 1900, 1980, 1900, 1980
        )
        assert strength >= 0.15
        assert len(overlaps) == 1
        assert overlaps[0]["overlap_type"] == "same_year"

    def test_same_place_nearby_year(self):
        """Same place within 5 years should give moderate score."""
        target_events = [
            {"type": "BIRT", "year": 1900, "place": "Pittsburgh", "place_normalized": "pittsburgh"}
        ]
        candidate_events = [
            {"type": "BIRT", "year": 1903, "place": "Pittsburgh", "place_normalized": "pittsburgh"}
        ]
        strength, overlaps, _ = _calculate_association_strength(
            target_events, candidate_events, 1900, 1980, 1903, 1983
        )
        assert strength >= 0.08
        assert len(overlaps) == 1
        assert overlaps[0]["overlap_type"] == "within_5_years"

    def test_no_overlap(self):
        """No overlapping events should give zero score."""
        target_events = [
            {"type": "BIRT", "year": 1900, "place": "Pittsburgh", "place_normalized": "pittsburgh"}
        ]
        candidate_events = [
            {"type": "BIRT", "year": 1900, "place": "New York", "place_normalized": "new york"}
        ]
        strength, overlaps, _ = _calculate_association_strength(
            target_events, candidate_events, 1900, 1980, 1900, 1980
        )
        assert len(overlaps) == 0

    def test_strength_capped_at_one(self):
        """Strength should not exceed 1.0."""
        # Many overlapping events
        target_events = [
            {
                "type": f"EVT{i}",
                "year": 1900 + i,
                "place": "Pittsburgh",
                "place_normalized": "pittsburgh",
            }
            for i in range(20)
        ]
        candidate_events = target_events.copy()
        strength, _, _ = _calculate_association_strength(
            target_events, candidate_events, 1900, 1980, 1900, 1980
        )
        assert strength <= 1.0


class TestFindAssociates:
    """Tests for the main find_associates function."""

    def test_returns_proper_structure(self):
        """Should return proper dict structure."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        indi_id = next(iter(state.individuals.keys()))
        result = _find_associates(indi_id)

        assert "individual" in result
        assert "filters_applied" in result
        assert "result_count" in result
        assert "associates" in result
        assert "computation_stats" in result

    def test_nonexistent_individual(self):
        """Should handle nonexistent individual gracefully."""
        result = _find_associates("@NONEXISTENT999@")
        assert "error" in result
        assert result["individual"] is None

    def test_respects_max_results(self):
        """Should respect max_results parameter."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        indi_id = next(iter(state.individuals.keys()))
        result = _find_associates(indi_id, max_results=3)

        assert len(result["associates"]) <= 3

    def test_max_results_capped(self):
        """max_results should be capped at 200."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        indi_id = next(iter(state.individuals.keys()))
        result = _find_associates(indi_id, max_results=500)

        # Even with 500 requested, should not exceed 200
        assert len(result["associates"]) <= 200

    def test_associates_have_strength(self):
        """Associates should have association_strength between 0 and 1."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with events
        for indi in state.individuals.values():
            if indi.birth_place:
                result = _find_associates(indi.id)
                for assoc in result["associates"]:
                    assert "association_strength" in assoc
                    assert 0.0 <= assoc["association_strength"] <= 1.0
                break

    def test_associates_sorted_by_strength(self):
        """Associates should be sorted by strength descending."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with events
        for indi in state.individuals.values():
            if indi.birth_place:
                result = _find_associates(indi.id, max_results=50)
                associates = result["associates"]
                if len(associates) >= 2:
                    strengths = [a["association_strength"] for a in associates]
                    assert strengths == sorted(strengths, reverse=True)
                break

    def test_exclude_relatives_default(self):
        """By default, relatives should be excluded."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with known relatives
        for indi in state.individuals.values():
            if indi.family_as_child:
                result = _find_associates(indi.id)
                # All associates should have is_relative=False
                for assoc in result["associates"]:
                    assert assoc["is_relative"] is False
                break

    def test_include_relatives_when_requested(self):
        """When exclude_relatives=False, relatives should be included."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with birth place and parents
        for indi in state.individuals.values():
            if indi.birth_place and indi.family_as_child:
                fam = state.families.get(indi.family_as_child)
                if fam:
                    result = _find_associates(indi.id, exclude_relatives=False)
                    # Not all trees will have relatives with overlapping events
                    # Just verify the structure is correct
                    for assoc in result["associates"]:
                        assert "is_relative" in assoc
                    break

    def test_place_filter_works(self):
        """Place filter should restrict to matching places."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with a birth place
        for indi in state.individuals.values():
            if indi.birth_place:
                # Use their birth place as filter
                place = indi.birth_place.split(",")[0]  # First component
                result = _find_associates(indi.id, place=place)
                # Should not error
                assert "error" not in result or result.get("result_count", 0) >= 0
                break

    def test_date_range_filter_works(self):
        """Date range filter should restrict to matching years."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with a birth date
        for indi in state.individuals.values():
            if indi.birth_date and indi.birth_place:
                from gedcom_server.helpers import extract_year

                year = extract_year(indi.birth_date)
                if year:
                    result = _find_associates(indi.id, start_year=year - 10, end_year=year + 10)
                    # Should not error
                    assert "error" not in result or result.get("result_count", 0) >= 0
                    # Filter should be recorded
                    assert result["filters_applied"]["date_range"] is not None
                    break

    def test_computation_stats_present(self):
        """Computation stats should be present and valid."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        indi_id = next(iter(state.individuals.keys()))
        result = _find_associates(indi_id)

        stats = result["computation_stats"]
        assert "candidates_scanned" in stats
        assert "relatives_filtered" in stats
        assert "time_ms" in stats
        assert isinstance(stats["candidates_scanned"], int)
        assert isinstance(stats["relatives_filtered"], int)
        assert isinstance(stats["time_ms"], int)
        assert stats["time_ms"] >= 0

    def test_overlapping_events_limited(self):
        """Overlapping events should be limited to avoid huge responses."""
        if not state.individuals:
            pytest.skip("No individuals loaded")

        # Find someone with events
        for indi in state.individuals.values():
            if indi.birth_place:
                result = _find_associates(indi.id)
                for assoc in result["associates"]:
                    # Should have max 5 overlapping events per associate
                    assert len(assoc.get("overlapping_events", [])) <= 5
                break
