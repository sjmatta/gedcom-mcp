"""Small, explicit genealogy examples that exercise answer correctness."""

import numpy as np
import pytest
from ged4py import GedcomReader

from gedcom_server import semantic, state
from gedcom_server.core import (
    _build_ancestor_set,
    _get_relationship,
    _get_relationship_with_cache,
)
from gedcom_server.events import (
    _get_family_events,
    _get_family_timeline,
    _get_military_service,
    _get_timeline,
    _is_military_event,
)
from gedcom_server.models import Event, Family, Individual
from gedcom_server.narrative import _get_biography
from gedcom_server.parsing import parse_events_from_record


@pytest.fixture
def lineage(monkeypatch):
    people = {
        f"@I{n}@": Individual(id=f"@I{n}@", family_as_child=f"@F{n}@" if n < 5 else None)
        for n in range(6)
    }
    families = {
        f"@F{n}@": Family(id=f"@F{n}@", husband_id=f"@I{n + 1}@", children_ids=[f"@I{n}@"])
        for n in range(5)
    }
    monkeypatch.setattr(state, "individuals", people)
    monkeypatch.setattr(state, "families", families)
    return people


@pytest.mark.parametrize(
    "depth, descendant, ancestor",
    [
        (1, "child", "parent"),
        (2, "grandchild", "grandparent"),
        (3, "great-grandchild", "great-grandparent"),
        (4, "second great-grandchild", "second great-grandparent"),
        (5, "third great-grandchild", "third great-grandparent"),
    ],
)
def test_relationship_direction_at_every_depth(lineage, depth, descendant, ancestor):
    older = f"@I{depth}@"
    cache = {id_: _build_ancestor_set(id_) for id_ in lineage}
    for first, second, expected in [("@I0@", older, descendant), (older, "@I0@", ancestor)]:
        assert _get_relationship(first, second)["relationship"] == expected
        assert _get_relationship_with_cache(first, second, cache)["relationship"] == expected


def test_all_timelines_order_days_and_months_and_preserve_qualifiers(lineage):
    dates = [
        None,
        "1 DEC 1900",
        "10 FEB 1900",
        "2 JAN 1900",
        "ABT 1899",
        "BET 1880 AND 1885",
        "FROM 1910 TO 1912",
        "(date unknown)",
    ]
    lineage["@I0@"].events = [Event(type="EVEN", date=date) for date in dates]
    expected = [
        "BET 1880 AND 1885",
        "ABT 1899",
        "2 JAN 1900",
        "10 FEB 1900",
        "1 DEC 1900",
        "FROM 1910 TO 1912",
        None,
        "(date unknown)",
    ]
    for events in [_get_timeline("I0"), _get_family_timeline(["I0"]), _get_family_events("F0")]:
        assert [event["date"] for event in events] == expected


@pytest.mark.parametrize(
    "text",
    [
        "Hardware merchant",
        "General store owner",
        "Private funeral service",
        "Shipping company",
        "Award recipient",
        "Served dinner to neighbors",
    ],
)
def test_civilian_descriptions_are_not_military_service(text):
    assert not _is_military_event(Event(type="OCCU", description=text))
    assert not _is_military_event(Event(type="EVEN", notes=[text]))


def test_military_results_explain_explicit_and_inferred_evidence(lineage):
    lineage["@I0@"].events = [
        Event(type="_MILT"),
        Event(type="EVEN", notes=["His brother served in the Army"]),
        Event(type="OCCU", description="Hardware merchant"),
    ]
    events = _get_military_service()["individuals"][0]["military_events"]
    assert [event["military_evidence"]["basis"] for event in events] == [
        "explicit_tag",
        "possible_reference",
    ]
    assert events[1]["military_evidence"]["matched_text"] == "Army"


def test_imported_events_reach_biography_and_embedding_text(tmp_path, lineage):
    path = tmp_path / "events.ged"
    path.write_text(
        "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n2 FORM LINEAGE-LINKED\n1 CHAR UTF-8\n"
        "0 @I0@ INDI\n1 NAME Example /Person/\n1 OCCU Coal miner\n"
        "1 BURI\n2 DATE 1 JAN 1900\n2 PLAC Example Cemetery\n"
        "2 SOUR @S1@\n3 PAGE 42\n2 NOTE Burial register\n"
        "1 CHR\n2 DATE 1 JAN 1820\n1 BAPM\n2 DATE 2 JAN 1820\n"
        "1 _MILT\n2 TYPE Army enlistment\n1 EVEN Descriptive value\n"
        "2 TYPE Custom event\n1 BIRT Y\n0 TRLR\n"
    )
    with GedcomReader(str(path)) as reader:
        events = parse_events_from_record(next(reader.records0("INDI")))
    assert [event.type for event in events] == [
        "OCCU",
        "BURI",
        "CHR",
        "BAPM",
        "_MILT",
        "EVEN",
        "BIRT",
    ]
    lineage["@I0@"].events = events
    biography = _get_biography("I0")
    assert biography["events"][0]["description"] == "Coal miner"
    assert biography["events"][1]["citations"][0]["page"] == "42"
    assert biography["events"][1]["notes"] == ["Burial register"]
    assert events[4].description == "Army enlistment"
    assert events[5].description == "Custom event: Descriptive value"
    assert events[6].description is None
    text = semantic._build_embedding_text("@I0@")
    assert "Coal miner" in text
    assert "Example Cemetery" in text


@pytest.mark.parametrize("version", [None, semantic.CONTENT_VERSION - 1])
def test_old_semantic_cache_is_rebuilt_after_parser_changes(tmp_path, monkeypatch, version):
    path = tmp_path / "tree.ged"
    path.write_text("0 HEAD\n0 TRLR\n")
    monkeypatch.setattr(state, "GEDCOM_FILE", path)
    metadata = {} if version is None else {"content_version": version}
    np.savez_compressed(
        semantic._get_cache_path(),
        gedcom_hash=semantic._compute_gedcom_hash(),
        model_name=semantic.MODEL_NAME,
        embeddings=np.zeros((1, 384)),
        ids=np.array(["@I0@"]),
        texts=np.array(["old content"]),
        **metadata,
    )
    assert semantic._load_cache() is False
