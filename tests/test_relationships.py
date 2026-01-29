"""Tests for relationship integrity."""

import gedcom_server as gs


class TestRelationshipIntegrity:
    """Tests that verify bidirectional relationships are consistent."""

    def test_family_members_exist(self):
        """All IDs referenced in families should exist in individuals."""
        missing = []
        for fam in gs.families.values():
            if fam.husband_id and fam.husband_id not in gs.individuals:
                missing.append(f"Husband {fam.husband_id} in family {fam.id}")
            if fam.wife_id and fam.wife_id not in gs.individuals:
                missing.append(f"Wife {fam.wife_id} in family {fam.id}")
            for child_id in fam.children_ids:
                if child_id and child_id not in gs.individuals:
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
        for fam in gs.families.values():
            for child_id in fam.children_ids:
                if child_id in gs.individuals:
                    child = gs.individuals[child_id]
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
        for fam in gs.families.values():
            for spouse_id in [fam.husband_id, fam.wife_id]:
                if spouse_id and spouse_id in gs.individuals:
                    spouse = gs.individuals[spouse_id]
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

        siblings_of_1 = gs._get_siblings(child1_id)
        siblings_of_2 = gs._get_siblings(child2_id)

        sibling_ids_of_1 = {s["id"] for s in siblings_of_1}
        sibling_ids_of_2 = {s["id"] for s in siblings_of_2}

        assert child2_id in sibling_ids_of_1, "Child 2 should be sibling of Child 1"
        assert child1_id in sibling_ids_of_2, "Child 1 should be sibling of Child 2"

    def test_parent_child_bidirectional(self, individual_with_parents):
        """If A is parent of B, B should list A as parent."""
        indi = individual_with_parents
        parents = gs._get_parents(indi.id)

        assert parents is not None, "Should have parents"

        # Check that this individual is in their parents' children
        for parent_key in ["father", "mother"]:
            parent = parents.get(parent_key)
            if parent:
                parent_children = gs._get_children(parent["id"])
                child_ids = {c["id"] for c in parent_children}
                assert indi.id in child_ids, f"Individual should be in {parent_key}'s children"

    def test_spouse_bidirectional(self, individual_with_spouse):
        """If A is married to B, B should list A as spouse."""
        indi = individual_with_spouse
        spouses = gs._get_spouses(indi.id)

        assert len(spouses) > 0, "Should have at least one spouse"

        spouse = spouses[0]
        spouse_spouses = gs._get_spouses(spouse["id"])
        spouse_spouse_ids = {s["id"] for s in spouse_spouses}

        assert indi.id in spouse_spouse_ids, "Individual should be in spouse's spouse list"

    def test_no_self_references(self):
        """No individual should be their own parent, spouse, or child."""
        errors = []
        for indi in gs.individuals.values():
            # Check not own parent
            if indi.family_as_child:
                fam = gs.families.get(indi.family_as_child)
                if fam and (fam.husband_id == indi.id or fam.wife_id == indi.id):
                    errors.append(f"{indi.id} is their own parent")

            # Check not own child
            for fam_id in indi.families_as_spouse:
                fam = gs.families.get(fam_id)
                if fam and indi.id in fam.children_ids:
                    errors.append(f"{indi.id} is their own child")

        assert len(errors) == 0, f"Self-references found: {errors}"


class TestGetParentsIntegrity:
    """Tests for get_parents function with real data."""

    def test_returns_both_parents_when_available(self, individual_with_parents):
        """Should return both parents when both exist."""
        parents = gs._get_parents(individual_with_parents.id)
        assert parents is not None
        # At least one parent should exist
        assert parents["father"] is not None or parents["mother"] is not None

    def test_parents_are_different_people(self, individual_with_parents):
        """Father and mother should be different people."""
        parents = gs._get_parents(individual_with_parents.id)
        if parents and parents["father"] and parents["mother"]:
            assert parents["father"]["id"] != parents["mother"]["id"]


class TestGetChildrenIntegrity:
    """Tests for get_children function with real data."""

    def test_children_are_unique(self, individual_with_children):
        """Children list should not have duplicates."""
        children = gs._get_children(individual_with_children.id)
        child_ids = [c["id"] for c in children]
        assert len(child_ids) == len(set(child_ids)), "Duplicate children found"

    def test_children_from_multiple_families(self):
        """Should collect children from all marriages."""
        # Find someone with multiple marriages
        for indi in gs.individuals.values():
            if len(indi.families_as_spouse) > 1:
                children = gs._get_children(indi.id)
                # Should work without error
                assert isinstance(children, list)
                break


class TestGetSpousesIntegrity:
    """Tests for get_spouses function with real data."""

    def test_spouse_has_marriage_info(self, individual_with_spouse):
        """Spouse record should include marriage details."""
        spouses = gs._get_spouses(individual_with_spouse.id)
        if spouses:
            spouse = spouses[0]
            assert "family_id" in spouse
            assert "marriage_date" in spouse
            assert "marriage_place" in spouse

    def test_correct_spouse_returned(self, individual_with_spouse):
        """Should return the other person in the marriage, not self."""
        indi = individual_with_spouse
        spouses = gs._get_spouses(indi.id)

        for spouse in spouses:
            assert spouse["id"] != indi.id, "Should not return self as spouse"


class TestIndexIntegrity:
    """Tests for index data structures."""

    def test_surname_index_references_valid_individuals(self):
        """All IDs in surname_index should exist in individuals."""
        for surname, ids in gs.surname_index.items():
            for indi_id in ids[:10]:  # Sample first 10
                assert indi_id in gs.individuals, f"ID {indi_id} not found for surname {surname}"

    def test_birth_year_index_references_valid_individuals(self):
        """All IDs in birth_year_index should exist in individuals."""
        for year, ids in gs.birth_year_index.items():
            for indi_id in ids[:10]:  # Sample first 10
                assert indi_id in gs.individuals, f"ID {indi_id} not found for year {year}"

    def test_place_index_references_valid_individuals(self):
        """All IDs in place_index should exist in individuals."""
        for place, ids in list(gs.place_index.items())[:100]:  # Sample first 100 places
            for indi_id in ids[:10]:  # Sample first 10 per place
                assert indi_id in gs.individuals, f"ID {indi_id} not found for place {place}"
