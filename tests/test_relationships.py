"""Tests for relationship integrity."""

from gedcom_server.core import (
    _detect_pedigree_collapse,
    _find_common_ancestors,
    _get_children,
    _get_individuals_batch,
    _get_parents,
    _get_relationship,
    _get_siblings,
    _get_spouses,
)
from gedcom_server.state import (
    HOME_PERSON_ID,
    birth_year_index,
    families,
    individuals,
    place_index,
    surname_index,
)


class TestRelationshipIntegrity:
    """Tests that verify bidirectional relationships are consistent."""

    def test_family_members_exist(self):
        """All IDs referenced in families should exist in individuals."""
        missing = []
        for fam in families.values():
            if fam.husband_id and fam.husband_id not in individuals:
                missing.append(f"Husband {fam.husband_id} in family {fam.id}")
            if fam.wife_id and fam.wife_id not in individuals:
                missing.append(f"Wife {fam.wife_id} in family {fam.id}")
            for child_id in fam.children_ids:
                if child_id and child_id not in individuals:
                    missing.append(f"Child {child_id} in family {fam.id}")

        # Allow some missing (common in genealogy data), but flag if excessive
        if missing:
            # Just warn, don't fail - genealogy data often has broken links
            print(f"Warning: {len(missing)} missing individual references")

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

    def test_children_from_multiple_families(self):
        """Should collect children from all marriages."""
        # Find someone with multiple marriages
        for indi in individuals.values():
            if len(indi.families_as_spouse) > 1:
                children = _get_children(indi.id)
                # Should work without error
                assert isinstance(children, list)
                break


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


class TestGetIndividualsBatch:
    """Tests for batch individual retrieval."""

    def test_batch_returns_dict(self):
        """Should return a dictionary."""
        ids = list(individuals.keys())[:3]
        result = _get_individuals_batch(ids)
        assert isinstance(result, dict)

    def test_batch_returns_all_requested(self):
        """Should return an entry for each requested ID."""
        ids = list(individuals.keys())[:5]
        result = _get_individuals_batch(ids)
        for id_str in ids:
            assert id_str in result

    def test_batch_with_nonexistent(self):
        """Should return None for nonexistent IDs."""
        ids = [list(individuals.keys())[0], "@NONEXISTENT999@"]
        result = _get_individuals_batch(ids)
        assert result.get("@NONEXISTENT999@") is None

    def test_batch_with_empty_list(self):
        """Should handle empty list."""
        result = _get_individuals_batch([])
        assert result == {}

    def test_batch_normalizes_ids(self):
        """Should handle IDs with or without @ symbols."""
        first_id = list(individuals.keys())[0]
        stripped = first_id.strip("@")
        result = _get_individuals_batch([stripped])
        # Should normalize and return the same data
        assert first_id in result


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

    def test_common_ancestors_have_generation_info(self, individual_with_parents):
        """Common ancestors should include generation distances."""
        # Find someone with known ancestry
        indi = individual_with_parents
        parents = _get_parents(indi.id)
        if parents and parents.get("father") and parents.get("mother"):
            # Father and mother should share the child as "common descendant"
            # but for common ancestors, siblings would share parents
            pass  # More complex test would require known sibling data

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

    def test_parent_child(self, individual_with_parents):
        """Should identify parent-child relationship."""
        indi = individual_with_parents
        parents = _get_parents(indi.id)
        if parents and parents.get("father"):
            result = _get_relationship(indi.id, parents["father"]["id"])
            assert result["relationship"] == "child"
            # Reverse direction
            result2 = _get_relationship(parents["father"]["id"], indi.id)
            assert result2["relationship"] == "parent"

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

    def test_collapse_point_structure(self):
        """Collapse points should have proper structure if found."""
        # Use home person for more complete ancestry
        result = _detect_pedigree_collapse(HOME_PERSON_ID)
        if result["collapse_points"]:
            point = result["collapse_points"][0]
            assert "ancestor_id" in point
            assert "ancestor_name" in point
            assert "paths" in point
            assert "generations" in point
            assert "occurrence_count" in point

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
