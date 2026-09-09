"""Regression coverage for geography, graph bounds, and family provenance."""

import json
from collections import defaultdict
from unittest.mock import Mock

import pytest

from gedcom_server import core, semantic, spatial, state
from gedcom_server.events import _get_family_timeline, _get_timeline
from gedcom_server.geocoding import local_geocode
from gedcom_server.helpers import create_place
from gedcom_server.models import Family, Individual
from gedcom_server.narrative import _get_biography
from gedcom_server.parsing import load_gedcom
from gedcom_server.relationships import _get_parent_families, _get_relationship_to_me


@pytest.fixture
def private_tree(tmp_path, monkeypatch):
    path = tmp_path / "families.ged"
    path.write_text(
        "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n2 FORM LINEAGE-LINKED\n1 CHAR UTF-8\n"
        "0 @S1@ SOUR\n1 TITL Marriage register\n"
        "0 @I1@ INDI\n1 NAME Child /Example/\n1 FAMC @F1@\n2 PEDI birth\n"
        "1 FAMC @F2@\n2 PEDI adopted\n1 FAMC @F3@\n2 STAT disproven\n"
        "0 @I2@ INDI\n1 NAME Birth /Parent/\n1 FAMS @F1@\n"
        "0 @I3@ INDI\n1 NAME Adoptive /Parent/\n1 FAMS @F2@\n"
        "0 @I4@ INDI\n1 NAME Ambiguous /Child/\n1 FAMC @F1@\n1 FAMC @F2@\n"
        "0 @I5@ INDI\n1 NAME Other /Parent/\n1 FAMS @F1@\n"
        "0 @F1@ FAM\n1 HUSB @I2@\n1 WIFE @I5@\n1 CHIL @I1@\n1 CHIL @I4@\n"
        "1 MARR\n2 DATE 1 JAN 1980\n2 SOUR @S1@\n3 PAGE 17\n"
        "1 DIV\n2 DATE 1 JAN 1990\n2 NOTE Court record\n"
        "0 @F2@ FAM\n1 HUSB @I3@\n1 CHIL @I1@\n1 CHIL @I4@\n0 TRLR\n"
    )
    for name in ("individuals", "families", "sources", "repositories", "places"):
        monkeypatch.setattr(state, name, {})
    for name in ("surname_index", "birth_year_index", "place_index", "individual_places"):
        monkeypatch.setattr(state, name, defaultdict(list))
    monkeypatch.setattr(state, "GEDCOM_FILE", path)
    monkeypatch.setattr(state, "HOME_PERSON_ID", None)
    monkeypatch.setenv("GEDCOM_HOME_PERSON_ID", "I1")
    load_gedcom()
    return path


def test_all_parent_links_and_qualifiers_survive_import(private_tree):
    child = state.individuals["@I1@"]
    assert len(child.parent_families) == 3
    assert child.family_as_child == "@F1@"
    assert child.parent_selection == "explicit_birth"
    ambiguous = _get_parent_families("I4")
    assert ambiguous["selected_family_id"] is None
    assert ambiguous["selection"] == "ambiguous"
    assert len(core._get_parents("I4")["parent_families"]) == 2


def test_family_events_reach_biography_timeline_and_embeddings(private_tree):
    events = state.families["@F1@"].events
    assert [event.type for event in events] == ["MARR", "DIV"]
    assert events[0].citations[0].source_title == "Marriage register"
    biography = _get_biography("I2")
    assert biography["family_events"][0]["citations"][0]["page"] == "17"
    assert [event["type"] for event in _get_timeline("I2")] == ["MARR", "DIV"]
    assert not _get_timeline("I1")  # Parents' divorce is not the child's own event.
    merged = _get_family_timeline(["I2", "I5"])
    assert len(merged) == 2  # Shared events appear once, owned by the family.
    assert "Court record" in semantic._build_embedding_text("@I2@")


def test_relationship_path_respects_selected_lineage(private_tree):
    birth = _get_relationship_to_me("I2")
    assert birth["relationship"] == "parent"
    assert birth["path"][0]["family_id"] == "@F1@"
    assert birth["path"][0]["pedigree"] == "birth"
    assert _get_relationship_to_me("I3")["relationship"] is None
    adopted = _get_relationship_to_me("I3", "adopted")
    assert adopted["relationship"].startswith("parent through qualified")
    assert adopted["path"][0]["to_id"] == state.HOME_PERSON_ID
    assert _get_relationship_to_me("I1")["relationship"] == "same person"


def test_relationship_path_depth_limit_reports_incomplete(private_tree, monkeypatch):
    monkeypatch.setattr(state, "HOME_PERSON_ID", "@I3@")
    result = _get_relationship_to_me("I2", "all", max_steps=1)
    assert result["relationship"] is None
    assert result["truncated"] is True


def test_local_geocoding_distinguishes_same_named_cities():
    illinois, confidence = local_geocode("Springfield, Illinois, USA")
    massachusetts, _ = local_geocode("Springfield, Massachusetts, USA")
    assert confidence == "high"
    assert illinois is not None and massachusetts is not None
    assert illinois != massachusetts
    assert 39 < illinois[0] < 40
    assert 42 < massachusetts[0] < 43
    assert local_geocode("Springfield")[0] is None
    assert local_geocode("Springfield, Imaginary State, USA")[0] is None
    assert local_geocode("Springfield, Unknown County, Illinois, USA")[0] is None


def test_nominatim_reports_ambiguity_instead_of_first_result(monkeypatch):
    response = Mock()
    response.json.return_value = [
        {"lat": "39.8", "lon": "-89.6", "display_name": "Springfield, Illinois"},
        {"lat": "42.1", "lon": "-72.6", "display_name": "Springfield, Massachusetts"},
    ]
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: response)
    monkeypatch.setattr(spatial, "_last_nominatim_request", float("-inf"))
    result = spatial._geocode_via_nominatim_full("Springfield")
    assert result["ambiguous"] is True
    assert result["coords"] is None
    assert len(result["candidates"]) == 2


def test_geocache_migration_preserves_full_query_results_and_hydrates_places(tmp_path, monkeypatch):
    path = tmp_path / "tree.ged"
    path.write_text("0 HEAD\n")
    first, second = create_place("Springfield, Illinois, USA"), create_place("London, UK")
    monkeypatch.setattr(state, "GEDCOM_FILE", path)
    monkeypatch.setattr(state, "places", {first.id: first, second.id: second})
    monkeypatch.setattr(spatial, "_geocache", {})
    monkeypatch.setattr(spatial, "_geocache_dirty", False)
    cache = spatial._get_cache_path()
    cache.write_text(
        json.dumps(
            {
                "gedcom_hash": spatial._compute_gedcom_hash(),
                "geocoded": {
                    first.id: {"lat": 0, "lon": 0, "source": "geonamescache", "confidence": "high"},
                    second.id: {
                        "lat": 51.5,
                        "lon": -0.1,
                        "source": "nominatim",
                        "confidence": "medium",
                    },
                },
            }
        )
    )
    assert spatial._load_geocache()
    assert first.id not in spatial._geocache
    assert spatial._geocode_place_full(second)[0] == (51.5, -0.1)
    assert second.latitude == 51.5
    spatial._save_geocache()
    assert json.loads(cache.read_text())["geocoder_version"] == 2


def test_cycle_and_pedigree_path_budgets(monkeypatch):
    people = {f"@I{n}@": Individual(id=f"@I{n}@", family_as_child=f"@F{n}@") for n in range(3)}
    families = {
        "@F0@": Family(id="@F0@", husband_id="@I1@", wife_id="@I2@"),
        "@F1@": Family(id="@F1@", husband_id="@I0@"),
        "@F2@": Family(id="@F2@", husband_id="@I1@"),
    }
    monkeypatch.setattr(state, "individuals", people)
    monkeypatch.setattr(state, "families", families)
    ancestors = core._build_ancestor_set("I0", 100)
    assert ancestors == {"@I1@": [1], "@I2@": [1]}
    collapse = core._detect_pedigree_collapse("I0")
    assert collapse["cycle_detected"] is True
    assert all(point["ancestor_id"] != "@I0@" for point in collapse["collapse_points"])
    monkeypatch.setattr(core, "MAX_PEDIGREE_PATHS", 1)
    assert core._detect_pedigree_collapse("I0")["truncated"] is True
    monkeypatch.setattr(core, "MAX_TREE_NODES", 1)
    assert core._get_ancestors("I0")["truncated"] is True
    monkeypatch.setattr(core, "MAX_GRAPH_NODES", 1)
    with pytest.raises(ValueError, match="incomplete"):
        core._build_ancestor_set("I0")
