"""Research gaps on a tree with deliberately planted problems."""

from pathlib import Path

import pytest

from gedcom_server import state
from gedcom_server.document import Document
from gedcom_server.research_gaps import research_gaps
from gedcom_server.tree_audit import audit_document
from gedcom_server.tree_projection import INDEXES, projection

PLANTED = Path(__file__).parent / "fixtures" / "planted.ged"


@pytest.fixture
def planted(tmp_path, monkeypatch):
    target = projection(PLANTED.read_bytes(), tmp_path)
    for key in INDEXES:
        monkeypatch.setattr(state, key, getattr(target, key))
    monkeypatch.setattr(state, "GEDCOM_FILE", PLANTED)
    monkeypatch.setattr(state, "HOME_PERSON_ID", "@I1@")


def kinds(result):
    return {(item["individual"]["id"], item["kind"]) for item in result["items"]}


def test_every_planted_problem_is_found_nearest_first(planted):
    result = research_gaps(generations=4)
    assert kinds(result) == {
        ("@I2@", "uncited_vital"),
        ("@I2@", "missing_parent"),
        ("@I3@", "conflicting_vital"),
        ("@I3@", "no_recorded_parents"),
        ("@I4@", "ambiguous_parents"),
        ("@I4@", "no_birth_record"),
    }
    generations = [item["generation"] for item in result["items"]]
    assert generations == sorted(generations)
    assert result["people_examined"] == 4  # ambiguous parents are not traversed
    assert all(item["next_read"] and item["reason"] for item in result["items"])
    missing = next(i for i in result["items"] if i["kind"] == "missing_parent")
    assert missing["family_id"] == "@F2@"


def test_generation_bound_is_reported_not_mistaken_for_end_of_line(planted):
    result = research_gaps(generations=0)
    assert result["items"] == []
    assert result["depth_limited_people"] == 1


def test_scope_pagination_and_inputs(planted):
    scoped = research_gaps("I3", generations=2)
    assert scoped["root"]["id"] == "@I3@"
    assert kinds(scoped) == {("@I3@", "conflicting_vital"), ("@I3@", "no_recorded_parents")}
    page = research_gaps(limit=2)
    assert len(page["items"]) == 2 and page["next_offset"] == 2 and page["total"] == 6
    with pytest.raises(ValueError, match="Unknown individual"):
        research_gaps("@NOPE@")
    with pytest.raises(ValueError, match="generations"):
        research_gaps(generations=11)
    with pytest.raises(ValueError, match="Tree changed"):
        research_gaps(expected_snapshot="stale")


def test_audit_flags_the_same_planted_evidence_problems():
    codes = {
        (issue["code"], tuple(issue["records"]))
        for issue in audit_document(Document(PLANTED.read_bytes()))["issues"]
    }
    assert ("uncited_vital_event", ("@I2@",)) in codes
    assert ("conflicting_facts", ("@I3@",)) in codes
    assert ("multiple_parent_families", ("@I4@",)) in codes


def test_formatting_and_precision_differences_are_not_conflicts():
    from gedcom_server.research_gaps import _conflicting, _date, _place

    assert _place("Pittsburgh, PA") == _place("Pittsburgh, Pennsylvania")
    assert _place("Indiana, PA") == "indiana pennsylvania"  # only the last word is a state
    assert _date("(31 January 1930)") == _date("31 JAN 1930")
    assert not _conflicting({_date("1894"), _date("10 FEB 1894")})
    assert not _conflicting({_place("Pennsylvania"), _place("McKeesport, PA")})
    assert _conflicting({_date("30 JAN 1930"), _date("31 JAN 1930")})
    assert _conflicting({_place("Austria"), _place("Hungary")})
