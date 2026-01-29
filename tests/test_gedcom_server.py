"""Tests for the GEDCOM server."""

from gedcom_server.core import (
    _get_ancestors,
    _get_children,
    _get_descendants,
    _get_family,
    _get_individual,
    _get_parents,
    _get_siblings,
    _get_spouses,
    _get_statistics,
    _search_by_birth,
    _search_by_place,
    _search_individuals,
)
from gedcom_server.state import (
    birth_year_index,
    families,
    individuals,
    place_index,
    surname_index,
)


class TestLoadedData:
    """Tests that verify the GEDCOM data loaded correctly."""

    def test_individuals_loaded(self):
        """Should load a large number of individuals."""
        assert len(individuals) > 10000

    def test_families_loaded(self):
        """Should load families."""
        assert len(families) > 1000

    def test_surname_index_built(self):
        """Should build surname index."""
        assert len(surname_index) > 100


class TestStatistics:
    """Tests for the get_statistics function."""

    def test_statistics_returns_dict(self):
        stats = _get_statistics()
        assert isinstance(stats, dict)

    def test_statistics_has_required_keys(self):
        stats = _get_statistics()
        required_keys = [
            "total_individuals",
            "total_families",
            "males",
            "females",
            "earliest_birth_year",
            "latest_birth_year",
            "unique_surnames",
            "top_surnames",
        ]
        for key in required_keys:
            assert key in stats, f"Missing key: {key}"

    def test_statistics_counts_are_positive(self):
        stats = _get_statistics()
        assert stats["total_individuals"] > 0
        assert stats["total_families"] > 0


class TestSearchIndividuals:
    """Tests for the search_individuals function."""

    def test_search_returns_list(self):
        results = _search_individuals("Smith")
        assert isinstance(results, list)

    def test_search_respects_max_results(self):
        results = _search_individuals("a", max_results=10)
        assert len(results) <= 10

    def test_search_result_has_required_fields(self):
        results = _search_individuals("a", max_results=1)
        if results:
            result = results[0]
            assert "id" in result
            assert "name" in result

    def test_search_is_case_insensitive(self):
        upper = _search_individuals("SMITH")
        lower = _search_individuals("smith")
        # Both should find the same people
        assert len(upper) == len(lower)


class TestGetIndividual:
    """Tests for the get_individual function."""

    def test_get_existing_individual(self):
        # Get any individual ID from the loaded data
        indi_id = next(iter(individuals.keys()))
        result = _get_individual(indi_id)
        assert result is not None
        assert result["id"] == indi_id

    def test_get_nonexistent_individual(self):
        result = _get_individual("NONEXISTENT999")
        assert result is None

    def test_handles_at_symbols(self):
        indi_id = next(iter(individuals.keys()))
        result = _get_individual(f"@{indi_id}@")
        assert result is not None


class TestGetFamily:
    """Tests for the get_family function."""

    def test_get_existing_family(self):
        fam_id = next(iter(families.keys()))
        result = _get_family(fam_id)
        assert result is not None
        assert result["id"] == fam_id

    def test_get_nonexistent_family(self):
        result = _get_family("NONEXISTENT999")
        assert result is None

    def test_family_has_children_list(self):
        fam_id = next(iter(families.keys()))
        result = _get_family(fam_id)
        assert "children" in result
        assert isinstance(result["children"], list)


class TestRelationships:
    """Tests for relationship functions."""

    def test_get_parents(self):
        # Find an individual with parents
        for indi in individuals.values():
            if indi.family_as_child:
                result = _get_parents(indi.id)
                assert result is not None
                assert "family_id" in result
                break

    def test_get_children(self):
        # Find an individual with children
        for indi in individuals.values():
            if indi.families_as_spouse:
                result = _get_children(indi.id)
                assert isinstance(result, list)
                break

    def test_get_spouses(self):
        # Find an individual with a spouse
        for indi in individuals.values():
            if indi.families_as_spouse:
                result = _get_spouses(indi.id)
                assert isinstance(result, list)
                break

    def test_get_siblings(self):
        # Find an individual with siblings (multiple children in same family)
        for fam in families.values():
            if len(fam.children_ids) > 1:
                result = _get_siblings(fam.children_ids[0])
                assert isinstance(result, list)
                break


class TestAncestorDescendant:
    """Tests for ancestor and descendant tree functions."""

    def test_get_ancestors_returns_dict(self):
        indi_id = next(iter(individuals.keys()))
        result = _get_ancestors(indi_id, generations=2)
        assert isinstance(result, dict)

    def test_get_ancestors_respects_generation_limit(self):
        # Find someone with ancestors
        for indi in individuals.values():
            if indi.family_as_child:
                result = _get_ancestors(indi.id, generations=1)
                # At generation 1, should have info but no grandparents
                if "father" in result and result["father"]:
                    # Father should not have his own parents in gen=1
                    assert "father" not in result["father"]
                break

    def test_get_descendants_returns_dict(self):
        indi_id = next(iter(individuals.keys()))
        result = _get_descendants(indi_id, generations=2)
        assert isinstance(result, dict)


class TestSearchByBirth:
    """Tests for birth search function."""

    def test_search_by_year(self):
        # Get a year that has people
        year = next(iter(birth_year_index.keys()))
        results = _search_by_birth(year=year)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_search_by_year_range(self):
        year = next(iter(birth_year_index.keys()))
        results = _search_by_birth(year=year, year_range=0)
        # Exact year match should still work
        assert isinstance(results, list)


class TestSearchByPlace:
    """Tests for place search function."""

    def test_search_by_place(self):
        # Get a place that exists
        place = next(iter(place_index.keys()))
        # Extract a word from the place
        word = place.split(",")[0].split()[0] if place else "a"
        results = _search_by_place(word)
        assert isinstance(results, list)

    def test_search_respects_max_results(self):
        results = _search_by_place("a", max_results=5)
        assert len(results) <= 5
