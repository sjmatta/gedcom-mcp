"""Tests for bulk operation tools."""

import pytest

from gedcom_server.core import _get_relationship_matrix, _get_surname_group
from gedcom_server.events import _get_events_batch
from gedcom_server.narrative import _get_biographies_batch
from gedcom_server.state import families, individuals, surname_index


class TestGetEventsBatch:
    """Tests for _get_events_batch."""

    def test_returns_events_for_valid_ids(self, sample_individual_id):
        """Should return events for valid individual IDs."""
        result = _get_events_batch([sample_individual_id])
        assert sample_individual_id in result
        assert isinstance(result[sample_individual_id], list)

    def test_returns_empty_list_for_invalid_id(self):
        """Should return empty list for IDs not found."""
        result = _get_events_batch(["@INVALID@"])
        assert "@INVALID@" in result
        assert result["@INVALID@"] == []

    def test_handles_multiple_ids(self):
        """Should handle multiple IDs in one call."""
        ids = list(individuals.keys())[:3]
        result = _get_events_batch(ids)
        assert len(result) == 3
        for indi_id in ids:
            assert indi_id in result

    def test_handles_empty_list(self):
        """Should handle empty input list."""
        result = _get_events_batch([])
        assert result == {}

    def test_normalizes_ids(self):
        """Should normalize IDs with or without @ symbols."""
        indi_id = next(iter(individuals.keys()))
        stripped_id = indi_id.strip("@")
        result = _get_events_batch([stripped_id])
        # Result should use normalized form
        assert f"@{stripped_id}@" in result


class TestGetBiographiesBatch:
    """Tests for _get_biographies_batch."""

    def test_returns_biography_for_valid_id(self, sample_individual_id):
        """Should return biography for valid individual ID."""
        result = _get_biographies_batch([sample_individual_id])
        assert sample_individual_id in result
        bio = result[sample_individual_id]
        assert bio is not None
        assert "name" in bio
        assert "vital_summary" in bio

    def test_returns_none_for_invalid_id(self):
        """Should return None for IDs not found."""
        result = _get_biographies_batch(["@INVALID@"])
        assert "@INVALID@" in result
        assert result["@INVALID@"] is None

    def test_handles_multiple_ids(self):
        """Should handle multiple IDs in one call."""
        ids = list(individuals.keys())[:3]
        result = _get_biographies_batch(ids)
        assert len(result) == 3
        for indi_id in ids:
            assert indi_id in result

    def test_biography_includes_family_names(self, individual_with_parents):
        """Should include parent names in biography."""
        result = _get_biographies_batch([individual_with_parents.id])
        bio = result[individual_with_parents.id]
        assert bio is not None
        assert "parents" in bio
        # Parents should be names, not IDs
        for parent in bio["parents"]:
            assert not parent.startswith("@")


class TestGetSurnameGroup:
    """Tests for _get_surname_group."""

    @pytest.fixture
    def sample_surname(self):
        """Get a surname that exists in the tree."""
        if surname_index:
            return next(iter(surname_index.keys()))
        pytest.skip("No surnames in index")

    def test_returns_individuals_for_valid_surname(self, sample_surname):
        """Should return individuals for a valid surname."""
        result = _get_surname_group(sample_surname)
        assert result["surname"] == sample_surname
        assert result["count"] > 0
        assert len(result["individuals"]) == result["count"]

    def test_returns_empty_for_invalid_surname(self):
        """Should return empty list for unknown surname."""
        result = _get_surname_group("ZZZZNOTASURNAME")
        assert result["surname"] == "ZZZZNOTASURNAME"
        assert result["count"] == 0
        assert result["individuals"] == []

    def test_case_insensitive_lookup(self, sample_surname):
        """Should find surname regardless of case."""
        result_lower = _get_surname_group(sample_surname.lower())
        result_upper = _get_surname_group(sample_surname.upper())
        assert result_lower["count"] == result_upper["count"]

    def test_includes_statistics(self, sample_surname):
        """Should include statistics about the surname group."""
        result = _get_surname_group(sample_surname)
        stats = result["statistics"]
        assert "earliest_birth" in stats
        assert "latest_birth" in stats
        assert "common_places" in stats
        assert "generation_count" in stats

    def test_include_spouses_flag(self, sample_surname):
        """Should optionally include spouses."""
        without_spouses = _get_surname_group(sample_surname, include_spouses=False)
        with_spouses = _get_surname_group(sample_surname, include_spouses=True)
        # With spouses should have >= individuals (might be same if no spouses)
        assert len(with_spouses["individuals"]) >= len(without_spouses["individuals"])

    def test_spouses_marked(self, sample_surname):
        """Spouses should be marked with is_spouse flag."""
        result = _get_surname_group(sample_surname, include_spouses=True)
        # Check if any spouses were added
        spouse_count = sum(1 for i in result["individuals"] if i.get("is_spouse"))
        # Count should match difference in totals
        without = _get_surname_group(sample_surname, include_spouses=False)
        assert spouse_count == len(result["individuals"]) - without["count"]


class TestGetRelationshipMatrix:
    """Tests for _get_relationship_matrix."""

    def test_returns_matrix_structure(self):
        """Should return proper matrix structure."""
        ids = list(individuals.keys())[:3]
        result = _get_relationship_matrix(ids)
        assert "individuals" in result
        assert "relationships" in result
        assert "pair_count" in result

    def test_correct_pair_count(self):
        """Should calculate correct number of pairs."""
        ids = list(individuals.keys())[:4]
        result = _get_relationship_matrix(ids)
        # n*(n-1)/2 pairs for n individuals
        expected_pairs = 4 * 3 // 2  # 6
        assert result["pair_count"] == expected_pairs
        assert len(result["relationships"]) == expected_pairs

    def test_handles_invalid_ids(self):
        """Should skip invalid IDs."""
        valid_id = next(iter(individuals.keys()))
        result = _get_relationship_matrix([valid_id, "@INVALID@"])
        # Only 1 valid individual means 0 pairs
        assert len(result["individuals"]) == 1
        assert result["pair_count"] == 0

    def test_handles_empty_list(self):
        """Should handle empty input."""
        result = _get_relationship_matrix([])
        assert result["individuals"] == []
        assert result["relationships"] == []
        assert result["pair_count"] == 0

    def test_sibling_relationship(self, family_with_multiple_children):
        """Should detect sibling relationship."""
        # Get two children from the same family
        child_ids = family_with_multiple_children.children_ids[:2]
        result = _get_relationship_matrix(child_ids)
        assert result["pair_count"] == 1
        rel = result["relationships"][0]
        assert rel["relationship"] == "sibling"

    def test_parent_child_relationship(self, individual_with_parents):
        """Should detect parent-child relationship."""
        indi_id = individual_with_parents.id
        fam = families.get(individual_with_parents.family_as_child)
        if not fam:
            pytest.skip("No family found")
        parent_id = fam.husband_id or fam.wife_id
        if not parent_id:
            pytest.skip("No parent found")

        result = _get_relationship_matrix([indi_id, parent_id])
        assert result["pair_count"] == 1
        rel = result["relationships"][0]
        assert rel["relationship"] in ("parent", "child")

    def test_relationship_includes_both_ids(self):
        """Each relationship should include both IDs."""
        ids = list(individuals.keys())[:3]
        result = _get_relationship_matrix(ids)
        for rel in result["relationships"]:
            assert "id1" in rel
            assert "id2" in rel
            assert "relationship" in rel
