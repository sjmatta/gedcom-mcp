"""Graph traversal, terminal ancestors, and relationship search depth."""

import pytest

from gedcom_server import state
from gedcom_server.core import _get_ancestors, _get_relationship, _traverse
from gedcom_server.models import Family, Individual


@pytest.mark.parametrize(
    "person_id, direction, expected",
    [
        ("I3", "parents", {"@I1@", "@I2@"}),
        ("I3", "children", {"@I5@", "@I6@"}),
        ("I3", "spouses", {"@I4@"}),
        ("I5", "siblings", {"@I6@"}),
    ],
)
def test_traverse_direct_relations(person_id, direction, expected):
    result = _traverse(person_id, direction)
    assert {person["id"] for person in result} == expected
    assert all(person["name"] and person["level"] == 1 for person in result)
    assert result == _traverse(f"@{person_id}@", direction)


@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_traverse_parent_levels(depth):
    result = _traverse("I5", "parents", depth=depth)
    expected = {"@I3@": 1, "@I4@": 1}
    if depth >= 2:
        expected.update({"@I1@": 2, "@I2@": 2})
    assert {person["id"]: person["level"] for person in result} == expected


def test_traverse_depth_cap(monkeypatch):
    people = {f"@I{n}@": Individual(id=f"@I{n}@", family_as_child=f"@F{n}@") for n in range(12)}
    families = {f"@F{n}@": Family(id=f"@F{n}@", husband_id=f"@I{n + 1}@") for n in range(11)}
    monkeypatch.setattr(state, "individuals", people)
    monkeypatch.setattr(state, "families", families)
    result = _traverse("I0", "parents", depth=100)
    assert [(person["id"], person["level"]) for person in result] == [
        (f"@I{n}@", n) for n in range(1, 11)
    ]


def test_traverse_spouse_cycle():
    result = _traverse("I3", "spouses", depth=3)
    assert [person["id"] for person in result] == ["@I4@"]


@pytest.mark.parametrize(
    "person_id, direction",
    [("NONEXISTENT999", "parents"), ("", "parents"), ("I3", "invalid_direction")],
)
def test_traverse_no_matches(person_id, direction):
    assert _traverse(person_id, direction) == []


@pytest.mark.parametrize("generations", [2, 10, 20])
def test_terminal_ancestors(generations):
    result = _get_ancestors("I5", generations=generations, filter="terminal")
    assert {person["id"]: (person["generation"], person["path"]) for person in result} == {
        "@I1@": (2, ["father", "father"]),
        "@I2@": (2, ["father", "mother"]),
        "@I4@": (1, ["mother"]),
    }


@pytest.mark.parametrize("person_id", ["", "NONEXISTENT999"])
def test_terminal_ancestors_missing_person(person_id):
    assert _get_ancestors(person_id, filter="terminal") == []


def test_unknown_ancestor_filter_uses_default_tree():
    assert _get_ancestors("I5", filter="unknown") == _get_ancestors("I5")


@pytest.mark.parametrize("max_generations", [1, 5, None])
def test_relationship_depth_keeps_direct_relations(max_generations):
    result = _get_relationship("I3", "I1", max_generations=max_generations)
    assert result["relationship"] == "child"
    assert result["individual_1"]["id"] == "@I3@"
    assert result["individual_2"]["id"] == "@I1@"


@pytest.mark.parametrize("max_generations, message", [(5, "5 generations"), (None, "in tree")])
def test_unrelated_message_reflects_search_depth(max_generations, message):
    result = _get_relationship("I1", "I4", max_generations=max_generations)
    assert "not related" in result["relationship"]
    assert message in result["relationship"]


def test_relationship_empty_ids():
    assert "error" in _get_relationship("", "")
