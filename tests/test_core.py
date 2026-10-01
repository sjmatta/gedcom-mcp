"""Core record lookup, search, and statistics contracts for the sample tree."""

import pytest

from gedcom_server.core import (
    _get_family,
    _get_individual,
    _get_statistics,
    _search_by_birth,
    _search_by_place,
    _search_individuals,
)
from gedcom_server.places import _get_place_cluster


@pytest.mark.parametrize("person_id", ["I1", "@I1@"])
def test_individual_lookup(person_id):
    person = _get_individual(person_id)
    assert person["id"] == "@I1@"
    assert person["full_name"] == "John SMITH"


def test_family_lookup():
    family = _get_family("@F2@")
    assert family["id"] == "@F2@"
    assert [child["id"] for child in family["children"]] == ["@I5@", "@I6@"]


def test_missing_family():
    assert _get_family("NONEXISTENT999") is None


def test_name_search_is_case_insensitive():
    upper = _search_individuals("SMITH")
    assert upper == _search_individuals("smith")
    assert {person["id"] for person in upper} == {"@I1@", "@I3@", "@I5@", "@I6@"}
    assert all(person["name"] for person in upper)


def test_name_search_limit():
    assert len(_search_individuals("Smith", max_results=2)) == 2


def test_birth_search_exact_year():
    assert [person["id"] for person in _search_by_birth(year=1930, year_range=0)] == ["@I1@"]


def test_place_search_limit():
    assert len(_search_by_place("New York", max_results=2)) == 2


def test_place_cluster_contents_and_limit():
    result = _get_place_cluster("New York", max_results=2)
    assert {
        "place",
        "result_count",
        "individuals",
        "place_variants",
        "event_breakdown",
    } <= result.keys()
    assert result["result_count"] == len(result["individuals"]) == 2
    assert result["place_variants"]
    assert result["event_breakdown"]


def test_statistics_contract():
    stats = _get_statistics()
    assert stats["total_individuals"] == 6
    assert stats["total_families"] == 2
    assert stats["males"] == stats["females"] == 3
    assert stats["unknown_sex"] == 0
    assert stats["unique_surnames"] == 3
    assert stats["earliest_birth_year"] == 1930
    assert stats["latest_birth_year"] == 1987
    assert stats["top_surnames"][0] == {"surname": "smith", "count": 4}
