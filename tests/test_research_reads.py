"""Evidence fidelity, date filtering, bounded reads and published revisions."""

from pathlib import Path

import pytest

from gedcom_server import state, writes
from gedcom_server.document import Document
from gedcom_server.research_reads import (
    get_group_timeline,
    get_individuals_batch,
    get_record,
    get_source,
    get_source_references,
    search_events,
    search_sources,
    year_interval,
)
from gedcom_server.tree_projection import INDEXES, projection
from gedcom_server.writes import TreeStore

SAMPLE = Path(__file__).parent / "fixtures" / "sample.ged"


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    raw = (
        SAMPLE.read_bytes()
        .replace(b"1 SEX M\n1 BIRT\n", b"1 SEX M\n1 _CUSTOM preserved\n1 BIRT\n", 1)
        .replace(
            b"3 PAGE Page 42\n",
            b"3 PAGE Page 42\n3 QUAY 2\n3 DATA\n4 TEXT original quote\n"
            b"5 CONT continued quote\n4 WWW https://example.org/image/42\n",
            1,
        )
        .replace(
            b"1 DEAT\n2 DATE 22 NOV 2010",
            b"1 BIRT\n2 DATE BET 1928 AND 1931\n2 PLAC Boston\n2 SOUR @S2@\n"
            b"1 DEAT\n2 DATE 22 NOV 2010",
            1,
        )
        .replace(b"0 @I2@ INDI", b"1 SOUR @S1@\n2 PAGE Person citation\n0 @I2@ INDI", 1)
        .replace(b"0 @F2@ FAM", b"1 SOUR @S1@\n2 PAGE Family citation\n0 @F2@ FAM", 1)
    )
    raw = raw.replace(
        b"0 @S1@ SOUR", b"0 @R1@ REPO\n1 NAME Town Archive\n1 ADDR Main Street\n0 @S1@ SOUR", 1
    ).replace(b"1 PUBL Boston, MA, 1900-2000\n", b"1 PUBL Boston, MA, 1900-2000\n1 REPO @R1@\n", 1)
    path = tmp_path / "tree.ged"
    path.write_bytes(raw)
    target = projection(raw, tmp_path)
    for key in INDEXES:
        monkeypatch.setattr(state, key, getattr(target, key))
    monkeypatch.setattr(state, "GEDCOM_FILE", path)
    monkeypatch.setattr(writes, "store", None)
    return path


def test_complete_record_subtree_paths_and_pagination(evidence):
    first = get_record("I1", limit=3)
    pages = [first["raw"]]
    offset = first["next_offset"]
    while offset is not None:
        page = get_record("I1", expected_snapshot=first["snapshot"], offset=offset, limit=3)
        pages.append(page["raw"])
        offset = page["next_offset"]
    doc = Document(evidence.read_bytes())
    start = doc.record("@I1@")
    assert "".join(pages) == "".join(line.raw for line in doc.lines[start : doc.end(start)])
    assert "_CUSTOM preserved" in "".join(pages)
    path = [{"tag": "BIRT", "index": 1}]
    alternate = get_record("I1", path)
    assert "BET 1928 AND 1931" in alternate["raw"]
    assert "15 MAR 1930" not in alternate["raw"]
    for field in alternate["items"]:
        assert doc.lines[doc.locate("@I1@", field["path"])].value == field["value"]
    with pytest.raises(ValueError, match="Record not found"):
        get_record("missing")
    with pytest.raises(ValueError, match="existing field"):
        get_record("I1", [{"tag": "BIRT", "index": 2}])


def test_source_lookup_and_reverse_citations_preserve_context(evidence):
    assert get_source("S1")["title"] == "Massachusetts Vital Records"
    assert get_source("S1")["repository"]["name"] == "Town Archive"
    assert get_source("missing") is None
    assert search_sources("COMMONWEALTH")["total"] == 1
    refs = get_source_references("S1")
    assert {r["record_type"] for r in refs["items"]} == {"INDI", "FAM"}
    cite = get_source_references("S1", page="Page 42")["items"][0]
    assert cite["fact_path"] == [{"tag": "BIRT", "index": 0}]
    assert "3 QUAY 2" in cite["raw"] and "continued quote" in cite["raw"]
    assert get_source_references("S1", page="42")["total"] == 0
    with pytest.raises(ValueError, match="Source not found"):
        get_source_references("I1")


def test_events_include_alternate_facts_and_family_events_once(evidence):
    found = search_events("birt", "Boston", 1929, 1929)
    assert found["total"] == 1
    assert found["items"][0]["date"] == "BET 1928 AND 1931"
    timeline = get_group_timeline(["I1", "@I1@", "I2"])
    marriages = [e for e in timeline["items"] if e["type"] == "MARR"]
    assert len(marriages) == 1
    assert marriages[0]["record_id"] == "@F1@"
    assert timeline["total"] == search_events(individual_ids=["I1", "I2"])["total"]
    assert get_group_timeline([])["total"] == 0
    assert get_individuals_batch(["I1", "@I1@", "missing"])["@missing@"] is None
    with pytest.raises(ValueError, match="Individuals not found"):
        get_group_timeline(["missing"])


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1800", (1800, 1800, "SIMPLE")),
        ("ABT 1800", (1800, 1800, "ABOUT")),
        ("BEF 1800", (None, 1800, "BEFORE")),
        ("AFT 1800", (1800, None, "AFTER")),
        ("FROM 1800", (1800, None, "FROM")),
        ("TO 1800", (None, 1800, "TO")),
        ("BET 1800 AND 1810", (1800, 1810, "RANGE")),
        ("(unknown)", (None, None, "PHRASE")),
    ],
)
def test_uncertain_dates(text, expected):
    assert year_interval(text) == expected


def test_unknown_dates_and_bounds(evidence):
    raw = evidence.read_bytes().replace(b"2 DATE 15 MAR 1930", b"2 DATE (unknown)")
    evidence.write_bytes(raw)
    assert search_events("BIRT", individual_ids=["I1"], start_year=1900)["total"] == 1
    assert (
        search_events("BIRT", individual_ids=["I1"], start_year=1900, include_undated=True)["total"]
        == 2
    )
    for fn, args in [
        (get_record, ["I1"]),
        (search_events, []),
        (search_sources, [""]),
        (get_source_references, ["S1"]),
    ]:
        with pytest.raises(ValueError, match="limit"):
            fn(*args, limit=501)
    with pytest.raises(ValueError, match="start_year"):
        search_events(start_year=2000, end_year=1900)
    with pytest.raises(ValueError, match="500"):
        get_individuals_batch(["I1"] * 501)


def test_snapshot_rejects_changed_baseline(evidence):
    page = get_record("I1", limit=1)
    evidence.write_bytes(evidence.read_bytes().replace(b"_CUSTOM preserved", b"_CUSTOM changed"))
    with pytest.raises(ValueError, match="Tree changed"):
        get_record("I1", offset=1, expected_snapshot=page["snapshot"])


def test_current_published_revision_reads(evidence, tmp_path, monkeypatch):
    tree = TreeStore(evidence, tmp_path / "store", "test")
    monkeypatch.setattr(writes, "store", tree)
    for key in (*INDEXES, "GEDCOM_FILE", "HOME_PERSON_ID"):
        monkeypatch.setattr(state, key, getattr(state, key))
    try:
        before = get_record("I1")
        proposal = tree.prepare(
            0,
            "Add evidence note",
            [{"op": "add_note", "record_id": "@I1@", "text": "new revision note"}],
        )
        tree.apply(proposal["proposal_id"], 0)
        after = get_record("I1")
        assert after["revision"] == 1 and "new revision note" in after["raw"]
        assert before["snapshot"] != after["snapshot"]
        with pytest.raises(ValueError, match="Tree changed"):
            search_sources("", expected_snapshot=before["snapshot"])
    finally:
        tree.close()
