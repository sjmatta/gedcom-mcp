"""Tests for relationship integrity."""

from gedcom_server.core import (
    _detect_pedigree_collapse,
    _find_common_ancestors,
    _get_children,
    _get_parents,
    _get_relationship,
    _get_siblings,
    _get_spouses,
)
from gedcom_server.state import (
    birth_year_index,
    families,
    individuals,
    place_index,
    surname_index,
)


class TestRelationshipIntegrity:
    """Tests that verify bidirectional relationships are consistent."""

    def test_children_reference_their_family(self):
        """Children should mostly have family_as_child pointing back to their family.

        Note: GEDCOM data from Ancestry.com may have some inconsistencies where
        a child is listed in multiple families (e.g., biological and adoptive).
        We allow a small percentage of mismatches.
        """
        mismatches = 0
        total_checked = 0
        for fam in families.values():
            for child_id in fam.children_ids:
                if child_id in individuals:
                    child = individuals[child_id]
                    total_checked += 1
                    if child.family_as_child != fam.id:
                        mismatches += 1
                    if total_checked >= 1000:  # Sample first 1000
                        break
            if total_checked >= 1000:
                break

        # Allow up to 5% mismatches for data quality issues
        mismatch_rate = mismatches / total_checked if total_checked > 0 else 0
        assert mismatch_rate < 0.05, (
            f"Too many mismatches: {mismatches}/{total_checked} ({mismatch_rate:.1%})"
        )

    def test_spouse_references_family(self):
        """Spouses should have the family in their families_as_spouse list."""
        mismatches = []
        sample_count = 0
        for fam in families.values():
            for spouse_id in [fam.husband_id, fam.wife_id]:
                if spouse_id and spouse_id in individuals:
                    spouse = individuals[spouse_id]
                    if fam.id not in spouse.families_as_spouse:
                        mismatches.append(
                            f"Spouse {spouse_id} doesn't have {fam.id} in families_as_spouse"
                        )
                    sample_count += 1
                    if sample_count >= 100:
                        break
            if sample_count >= 100:
                break

        assert len(mismatches) == 0, f"Found {len(mismatches)} mismatches: {mismatches[:5]}"

    def test_sibling_symmetry(self, family_with_multiple_children):
        """If A is sibling of B, B should be sibling of A."""
        fam = family_with_multiple_children
        child1_id = fam.children_ids[0]
        child2_id = fam.children_ids[1]

        siblings_of_1 = _get_siblings(child1_id)
        siblings_of_2 = _get_siblings(child2_id)

        sibling_ids_of_1 = {s["id"] for s in siblings_of_1}
        sibling_ids_of_2 = {s["id"] for s in siblings_of_2}

        assert child2_id in sibling_ids_of_1, "Child 2 should be sibling of Child 1"
        assert child1_id in sibling_ids_of_2, "Child 1 should be sibling of Child 2"

    def test_parent_child_bidirectional(self, individual_with_parents):
        """If A is parent of B, B should list A as parent."""
        indi = individual_with_parents
        parents = _get_parents(indi.id)

        assert parents is not None, "Should have parents"

        # Check that this individual is in their parents' children
        for parent_key in ["father", "mother"]:
            parent = parents.get(parent_key)
            if parent:
                parent_children = _get_children(parent["id"])
                child_ids = {c["id"] for c in parent_children}
                assert indi.id in child_ids, f"Individual should be in {parent_key}'s children"

    def test_spouse_bidirectional(self, individual_with_spouse):
        """If A is married to B, B should list A as spouse."""
        indi = individual_with_spouse
        spouses = _get_spouses(indi.id)

        assert len(spouses) > 0, "Should have at least one spouse"

        spouse = spouses[0]
        spouse_spouses = _get_spouses(spouse["id"])
        spouse_spouse_ids = {s["id"] for s in spouse_spouses}

        assert indi.id in spouse_spouse_ids, "Individual should be in spouse's spouse list"

    def test_no_self_references(self):
        """No individual should be their own parent, spouse, or child."""
        errors = []
        for indi in individuals.values():
            # Check not own parent
            if indi.family_as_child:
                fam = families.get(indi.family_as_child)
                if fam and (fam.husband_id == indi.id or fam.wife_id == indi.id):
                    errors.append(f"{indi.id} is their own parent")

            # Check not own child
            for fam_id in indi.families_as_spouse:
                fam = families.get(fam_id)
                if fam and indi.id in fam.children_ids:
                    errors.append(f"{indi.id} is their own child")

        assert len(errors) == 0, f"Self-references found: {errors}"


class TestGetParentsIntegrity:
    """Tests for get_parents function with real data."""

    def test_returns_both_parents_when_available(self, individual_with_parents):
        """Should return both parents when both exist."""
        parents = _get_parents(individual_with_parents.id)
        assert parents is not None
        # At least one parent should exist
        assert parents["father"] is not None or parents["mother"] is not None

    def test_parents_are_different_people(self, individual_with_parents):
        """Father and mother should be different people."""
        parents = _get_parents(individual_with_parents.id)
        if parents and parents["father"] and parents["mother"]:
            assert parents["father"]["id"] != parents["mother"]["id"]


class TestGetChildrenIntegrity:
    """Tests for get_children function with real data."""

    def test_children_are_unique(self, individual_with_children):
        """Children list should not have duplicates."""
        children = _get_children(individual_with_children.id)
        child_ids = [c["id"] for c in children]
        assert len(child_ids) == len(set(child_ids)), "Duplicate children found"


class TestGetSpousesIntegrity:
    """Tests for get_spouses function with real data."""

    def test_spouse_has_marriage_info(self, individual_with_spouse):
        """Spouse record should include marriage details."""
        spouses = _get_spouses(individual_with_spouse.id)
        if spouses:
            spouse = spouses[0]
            assert "family_id" in spouse
            assert "marriage_date" in spouse
            assert "marriage_place" in spouse

    def test_correct_spouse_returned(self, individual_with_spouse):
        """Should return the other person in the marriage, not self."""
        indi = individual_with_spouse
        spouses = _get_spouses(indi.id)

        for spouse in spouses:
            assert spouse["id"] != indi.id, "Should not return self as spouse"


class TestIndexIntegrity:
    """Tests for index data structures."""

    def test_surname_index_references_valid_individuals(self):
        """All IDs in surname_index should exist in individuals."""
        for surname, ids in surname_index.items():
            for indi_id in ids[:10]:  # Sample first 10
                assert indi_id in individuals, f"ID {indi_id} not found for surname {surname}"

    def test_birth_year_index_references_valid_individuals(self):
        """All IDs in birth_year_index should exist in individuals."""
        for year, ids in birth_year_index.items():
            for indi_id in ids[:10]:  # Sample first 10
                assert indi_id in individuals, f"ID {indi_id} not found for year {year}"

    def test_place_index_references_valid_individuals(self):
        """All IDs in place_index should exist in individuals."""
        for place, ids in list(place_index.items())[:100]:  # Sample first 100 places
            for indi_id in ids[:10]:  # Sample first 10 per place
                assert indi_id in individuals, f"ID {indi_id} not found for place {place}"


class TestFindCommonAncestors:
    """Tests for common ancestor finding."""

    def test_returns_dict_structure(self):
        """Should return properly structured dict."""
        ids = list(individuals.keys())[:2]
        result = _find_common_ancestors(ids[0], ids[1])
        assert "individual_1" in result
        assert "individual_2" in result
        assert "common_ancestors" in result

    def test_individual_info_included(self):
        """Should include individual names."""
        ids = list(individuals.keys())[:2]
        result = _find_common_ancestors(ids[0], ids[1])
        assert "id" in result["individual_1"]
        assert "name" in result["individual_1"]

    def test_nonexistent_individual(self):
        """Should handle nonexistent individual gracefully."""
        first_id = list(individuals.keys())[0]
        result = _find_common_ancestors(first_id, "@NONEXISTENT999@")
        assert "error" in result

    def test_same_person(self):
        """Should handle same person query."""
        first_id = list(individuals.keys())[0]
        result = _find_common_ancestors(first_id, first_id)
        # Same person has same ancestors
        assert "common_ancestors" in result


class TestGetRelationship:
    """Tests for relationship calculation."""

    def test_returns_dict_structure(self):
        """Should return properly structured dict."""
        ids = list(individuals.keys())[:2]
        result = _get_relationship(ids[0], ids[1])
        assert "individual_1" in result
        assert "individual_2" in result
        assert "relationship" in result

    def test_same_person(self):
        """Should identify same person."""
        first_id = list(individuals.keys())[0]
        result = _get_relationship(first_id, first_id)
        assert result["relationship"] == "same person"

    def test_sibling(self, family_with_multiple_children):
        """Should identify sibling relationship."""
        fam = family_with_multiple_children
        child1_id = fam.children_ids[0]
        child2_id = fam.children_ids[1]
        result = _get_relationship(child1_id, child2_id)
        assert result["relationship"] in ("sibling", "half-sibling")

    def test_spouse(self, individual_with_spouse):
        """Should identify spouse relationship."""
        indi = individual_with_spouse
        spouses = _get_spouses(indi.id)
        if spouses:
            result = _get_relationship(indi.id, spouses[0]["id"])
            assert result["relationship"] == "spouse"

    def test_nonexistent_individual(self):
        """Should handle nonexistent individual gracefully."""
        first_id = list(individuals.keys())[0]
        result = _get_relationship(first_id, "@NONEXISTENT999@")
        assert "error" in result

    def test_deep_ancestor_naming(self):
        """Should correctly name ancestors beyond great-grandparent."""
        from gedcom_server.core import _ancestor_name, _descendant_name

        # Test ancestor naming
        assert _ancestor_name(1) == "parent"
        assert _ancestor_name(2) == "grandparent"
        assert _ancestor_name(3) == "great-grandparent"
        assert _ancestor_name(4) == "second great-grandparent"
        assert _ancestor_name(5) == "third great-grandparent"
        assert _ancestor_name(10) == "eighth great-grandparent"
        assert _ancestor_name(21) == "19th great-grandparent"

        # Test descendant naming
        assert _descendant_name(1) == "child"
        assert _descendant_name(2) == "grandchild"
        assert _descendant_name(3) == "great-grandchild"
        assert _descendant_name(4) == "second great-grandchild"
        assert _descendant_name(5) == "third great-grandchild"


class TestDetectPedigreeCollapse:
    """Tests for pedigree collapse detection."""

    def test_returns_dict_structure(self):
        """Should return properly structured dict."""
        first_id = list(individuals.keys())[0]
        result = _detect_pedigree_collapse(first_id)
        assert "individual" in result
        assert "collapse_points" in result

    def test_individual_info_included(self):
        """Should include individual name."""
        first_id = list(individuals.keys())[0]
        result = _detect_pedigree_collapse(first_id)
        assert "id" in result["individual"]
        assert "name" in result["individual"]

    def test_nonexistent_individual(self):
        """Should handle nonexistent individual gracefully."""
        result = _detect_pedigree_collapse("@NONEXISTENT999@")
        assert "error" in result

    def test_respects_max_generations(self):
        """Should respect max_generations parameter."""
        first_id = list(individuals.keys())[0]
        # With very few generations, should still work
        result = _detect_pedigree_collapse(first_id, max_generations=2)
        assert "collapse_points" in result


def test_common_ancestors_include_generation_distances():
    result = _find_common_ancestors("I5", "I6")
    assert {
        person["id"]: (person["generations_from_1"], person["generations_from_2"])
        for person in result["common_ancestors"]
    } == {
        "@I3@": (1, 1),
        "@I4@": (1, 1),
        "@I1@": (2, 2),
        "@I2@": (2, 2),
    }
    assert all(person["name"] for person in result["common_ancestors"])
    distances = [
        person["generations_from_1"] + person["generations_from_2"]
        for person in result["common_ancestors"]
    ]
    assert distances == sorted(distances)
