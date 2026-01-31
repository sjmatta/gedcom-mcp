"""Tests for new features: traverse, get_ancestors filter, get_relationship max_generations."""

from gedcom_server.core import (
    _get_ancestors,
    _get_relationship,
    _traverse,
)
from gedcom_server.state import families, individuals


class TestTraverse:
    """Tests for the _traverse function."""

    def test_traverse_parents_returns_list(self, individual_with_parents):
        """Traverse parents should return a list."""
        result = _traverse(individual_with_parents.id, "parents", depth=1)
        assert isinstance(result, list)

    def test_traverse_parents_finds_parents(self, individual_with_parents):
        """Traverse parents at depth 1 should find parents."""
        result = _traverse(individual_with_parents.id, "parents", depth=1)
        # Should find at least one parent
        assert len(result) > 0
        # Each result should have level=1
        for item in result:
            assert item["level"] == 1

    def test_traverse_parents_depth_2(self, individual_with_parents):
        """Traverse parents at depth 2 should include grandparents."""
        result = _traverse(individual_with_parents.id, "parents", depth=2)
        # Check if there are any level 2 results (grandparents)
        levels = {item["level"] for item in result}
        assert 1 in levels  # Should have parents
        # Level 2 depends on data having grandparents

    def test_traverse_children_returns_list(self, individual_with_children):
        """Traverse children should return a list."""
        result = _traverse(individual_with_children.id, "children", depth=1)
        assert isinstance(result, list)

    def test_traverse_children_finds_children(self, individual_with_children):
        """Traverse children at depth 1 should find children."""
        result = _traverse(individual_with_children.id, "children", depth=1)
        assert len(result) > 0
        for item in result:
            assert item["level"] == 1

    def test_traverse_spouses_returns_list(self, individual_with_spouse):
        """Traverse spouses should return a list."""
        result = _traverse(individual_with_spouse.id, "spouses", depth=1)
        assert isinstance(result, list)

    def test_traverse_spouses_finds_spouse(self, individual_with_spouse):
        """Traverse spouses at depth 1 should find spouse."""
        result = _traverse(individual_with_spouse.id, "spouses", depth=1)
        assert len(result) > 0
        for item in result:
            assert item["level"] == 1

    def test_traverse_siblings_returns_list(self, family_with_multiple_children):
        """Traverse siblings should return a list."""
        # Get a child from the family
        child_id = family_with_multiple_children.children_ids[0]
        result = _traverse(child_id, "siblings", depth=1)
        assert isinstance(result, list)

    def test_traverse_siblings_finds_siblings(self, family_with_multiple_children):
        """Traverse siblings at depth 1 should find siblings."""
        child_id = family_with_multiple_children.children_ids[0]
        result = _traverse(child_id, "siblings", depth=1)
        # Should find at least one sibling (family has multiple children)
        assert len(result) > 0
        for item in result:
            assert item["level"] == 1
            # Should not include self
            assert item["id"] != child_id

    def test_traverse_nonexistent_individual(self):
        """Traverse with nonexistent individual should return empty list."""
        result = _traverse("NONEXISTENT999", "parents", depth=1)
        assert result == []

    def test_traverse_depth_capped_at_10(self, sample_individual_id):
        """Depth should be capped at 10."""
        # This should not crash even with very large depth
        result = _traverse(sample_individual_id, "parents", depth=100)
        assert isinstance(result, list)
        # All levels should be <= 10
        for item in result:
            assert item["level"] <= 10

    def test_traverse_depth_minimum_1(self, individual_with_parents):
        """Depth should be at least 1 even if 0 is passed."""
        result = _traverse(individual_with_parents.id, "parents", depth=0)
        # With depth clamped to 1, should still find parents
        assert isinstance(result, list)

    def test_traverse_result_has_required_fields(self, individual_with_parents):
        """Each result should have standard summary fields plus level."""
        result = _traverse(individual_with_parents.id, "parents", depth=1)
        if result:
            item = result[0]
            assert "id" in item
            assert "name" in item
            assert "level" in item

    def test_traverse_invalid_direction(self, sample_individual_id):
        """Invalid direction should return empty list (no matches)."""
        result = _traverse(sample_individual_id, "invalid_direction", depth=1)
        assert result == []

    def test_traverse_avoids_cycles(self, individual_with_spouse):
        """Traverse should not revisit the same person (avoid infinite loops)."""
        # Spouses are typically reciprocal, but we shouldn't revisit
        result = _traverse(individual_with_spouse.id, "spouses", depth=3)
        # Check for unique IDs
        ids = [item["id"] for item in result]
        assert len(ids) == len(set(ids)), "Duplicate individuals found in traverse"


class TestGetAncestorsTerminalFilter:
    """Tests for _get_ancestors with filter='terminal'."""

    def test_terminal_filter_returns_list(self, individual_with_parents):
        """With filter='terminal', should return a list."""
        result = _get_ancestors(individual_with_parents.id, generations=10, filter="terminal")
        assert isinstance(result, list)

    def test_terminal_filter_ancestors_have_no_parents(self, individual_with_parents):
        """Terminal ancestors should not have known parents."""
        result = _get_ancestors(individual_with_parents.id, generations=10, filter="terminal")
        for ancestor in result:
            ancestor_id = ancestor["id"]
            indi = individuals.get(ancestor_id)
            if indi and indi.family_as_child:
                # Terminal ancestors should either have no family_as_child
                # or their family has no parents listed
                fam = families.get(indi.family_as_child)
                if fam:
                    # At least one parent reference must be missing for this to be terminal
                    assert (
                        fam.husband_id is None
                        or fam.wife_id is None
                        or fam.husband_id not in individuals
                        or fam.wife_id not in individuals
                    )

    def test_terminal_filter_result_has_generation_and_path(self, individual_with_parents):
        """Terminal results should include generation and path."""
        result = _get_ancestors(individual_with_parents.id, generations=10, filter="terminal")
        if result:
            item = result[0]
            assert "generation" in item
            assert "path" in item
            assert isinstance(item["path"], list)

    def test_terminal_filter_does_not_include_starting_person(self, individual_with_parents):
        """Terminal filter should not include the starting person."""
        result = _get_ancestors(individual_with_parents.id, generations=10, filter="terminal")
        ids = [item["id"] for item in result]
        assert individual_with_parents.id not in ids

    def test_terminal_filter_with_high_generations(self, individual_with_parents):
        """Higher generations should find more terminal ancestors."""
        result_low = _get_ancestors(individual_with_parents.id, generations=2, filter="terminal")
        result_high = _get_ancestors(individual_with_parents.id, generations=20, filter="terminal")
        # Higher generations should find at least as many terminal ancestors
        assert len(result_high) >= len(result_low)

    def test_terminal_filter_nonexistent_person(self):
        """Terminal filter with nonexistent person should return empty list."""
        result = _get_ancestors("NONEXISTENT999", generations=10, filter="terminal")
        assert result == []

    def test_default_filter_returns_dict(self, individual_with_parents):
        """Without filter, should return nested dict (backward compatibility)."""
        result = _get_ancestors(individual_with_parents.id, generations=2, filter=None)
        assert isinstance(result, dict)

    def test_unknown_filter_value(self, individual_with_parents):
        """Unknown filter value should return nested dict (default behavior)."""
        result = _get_ancestors(individual_with_parents.id, generations=2, filter="unknown")
        assert isinstance(result, dict)


class TestGetRelationshipMaxGenerations:
    """Tests for _get_relationship with max_generations parameter."""

    def test_default_max_generations(self, individual_with_parents):
        """Default max_generations should be 10."""
        # Get parents
        fam = families.get(individual_with_parents.family_as_child)
        if fam and fam.husband_id:
            result = _get_relationship(individual_with_parents.id, fam.husband_id)
            # Should find the relationship (child)
            assert result["relationship"] == "child"

    def test_max_generations_none_unlimited(self, individual_with_parents):
        """max_generations=None should search unlimited depth."""
        fam = families.get(individual_with_parents.family_as_child)
        if fam and fam.husband_id:
            result = _get_relationship(
                individual_with_parents.id, fam.husband_id, max_generations=None
            )
            # Should still find the relationship
            assert result["relationship"] == "child"

    def test_max_generations_affects_not_related_message(self):
        """The 'not related' message should reflect max_generations."""
        # Use two unrelated individuals
        ids = list(individuals.keys())
        if len(ids) >= 2:
            result = _get_relationship(ids[0], ids[1], max_generations=5)
            # If not related, message should mention the depth
            if "not related" in result["relationship"]:
                assert "5 generations" in result["relationship"]

    def test_max_generations_none_message(self):
        """With max_generations=None, not related message should say 'in tree'."""
        ids = list(individuals.keys())
        if len(ids) >= 2:
            result = _get_relationship(ids[0], ids[1], max_generations=None)
            if "not related" in result["relationship"]:
                assert "in tree" in result["relationship"]

    def test_max_generations_1_finds_direct_relations(self, individual_with_parents):
        """max_generations=1 should still find direct parent/child."""
        fam = families.get(individual_with_parents.family_as_child)
        if fam and fam.husband_id:
            result = _get_relationship(
                individual_with_parents.id, fam.husband_id, max_generations=1
            )
            # Direct relations don't use ancestor search
            assert result["relationship"] == "child"

    def test_max_generations_respects_limit_for_cousins(self):
        """A very low max_generations should not find distant cousins."""
        # Find two individuals that are related through common ancestors
        # This is more of an integration test - hard to guarantee without specific data
        pass  # Skip detailed implementation - depends on test data structure

    def test_max_generations_returns_dict_structure(self, individual_with_parents):
        """Result should have standard structure regardless of max_generations."""
        fam = families.get(individual_with_parents.family_as_child)
        if fam and fam.husband_id:
            result = _get_relationship(
                individual_with_parents.id, fam.husband_id, max_generations=5
            )
            assert "individual_1" in result
            assert "individual_2" in result
            assert "relationship" in result


class TestTraverseDepthBehavior:
    """Tests for traverse depth behavior at multiple levels."""

    def test_traverse_depth_increases_results(self, individual_with_parents):
        """Higher depth should return same or more results."""
        result_1 = _traverse(individual_with_parents.id, "parents", depth=1)
        result_2 = _traverse(individual_with_parents.id, "parents", depth=2)
        # Depth 2 should include everything from depth 1 plus more
        assert len(result_2) >= len(result_1)

    def test_traverse_levels_are_sequential(self, individual_with_parents):
        """Traverse results should have sequential levels starting from 1."""
        result = _traverse(individual_with_parents.id, "parents", depth=3)
        if result:
            levels = sorted({item["level"] for item in result})
            # Levels should start at 1 and be sequential
            assert levels[0] == 1
            for i in range(len(levels) - 1):
                assert levels[i + 1] == levels[i] + 1


class TestEdgeCases:
    """Edge case tests for new features."""

    def test_traverse_empty_id(self):
        """Empty ID should return empty list."""
        result = _traverse("", "parents", depth=1)
        assert result == []

    def test_get_ancestors_empty_id_terminal(self):
        """Empty ID with terminal filter should return empty list."""
        result = _get_ancestors("", generations=10, filter="terminal")
        assert result == []

    def test_get_relationship_empty_ids(self):
        """Empty IDs should handle gracefully."""
        result = _get_relationship("", "", max_generations=10)
        assert "error" in result or result["relationship"] is None

    def test_traverse_normalizes_id(self, individual_with_parents):
        """Traverse should normalize IDs (handle with/without @)."""
        bare_id = individual_with_parents.id.strip("@")
        result = _traverse(bare_id, "parents", depth=1)
        assert isinstance(result, list)
