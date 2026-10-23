"""Append-only research ledger stored beside, never inside, the tree."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from gedcom_server import research_ledger, semantic, state
from gedcom_server.writes import INDEXES, TreeStore, projection

SAMPLE = Path(__file__).parent / "fixtures" / "sample.ged"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for key in (*INDEXES, "GEDCOM_FILE", "HOME_PERSON_ID"):
        monkeypatch.setattr(state, key, getattr(state, key))
    for key in ("_embeddings", "_embedding_ids", "_embedding_texts"):
        monkeypatch.setattr(semantic, key, getattr(semantic, key))
    baseline = tmp_path / "original.ged"
    baseline.write_bytes(SAMPLE.read_bytes())
    store = TreeStore(baseline, tmp_path / "store", "test-operator")
    store.publish(projection(baseline.read_bytes(), store.directory), store.export(0), 0)
    yield store
    store.close()


HYPOTHESIS = {
    "kind": "hypothesis",
    "statement": "I1 is the man in the 1860 census household",
    "subjects": ["I1"],
    "rivals": ["A namesake in another ward"],
    "predictions": ["The household includes his recorded wife"],
    "origin": "random_walk",
}
EVIDENCE = {
    "kind": "evidence",
    "stance": "supports",
    "source_type": "original",
    "information_type": "primary",
    "evidence_type": "indirect",
    "locator": {"source_id": "@S1@", "page": "Household 212"},
    "excerpt": "Anna, 24",
}
VERDICT = {
    "kind": "verdict",
    "status": "supported",
    "likelihood": "likely",
    "confidence": "moderate",
    "argument": "Ages and household match; the namesake is older.",
    "disconfirmation_search": "Searched the same census for other men of that name.",
}


def test_full_hypothesis_lifecycle_leaves_the_tree_unchanged(tree):
    before = tree.document(0)
    hypothesis = research_ledger.record(tree, HYPOTHESIS)
    hid = hypothesis["hypothesis_id"]
    assert hypothesis["subjects"] == ["@I1@"]
    assert research_ledger.read(tree, hypothesis_id=hid)["items"][0]["status"] == "open"
    research_ledger.record(tree, {**EVIDENCE, "hypothesis_id": hid})
    research_ledger.record(tree, {**VERDICT, "hypothesis_id": hid})
    item = research_ledger.read(tree, individual_id="@I1@")["items"][0]
    assert item["status"] == "supported" and item["evidence_count"] == 1
    assert [entry["kind"] for entry in item["entries"]] == ["hypothesis", "evidence", "verdict"]
    assert {entry["actor"] for entry in item["entries"]} == {"test-operator"}
    assert research_ledger.read(tree, status="open")["total"] == 0
    assert tree.revision == 0 and tree.document(0) == before


def test_entries_are_validated_and_ordered(tree):
    with pytest.raises(ValidationError):
        research_ledger.record(tree, {**HYPOTHESIS, "rivals": []})
    with pytest.raises(ValidationError):
        research_ledger.record(tree, {**EVIDENCE, "hypothesis_id": "x", "locator": {}})
    with pytest.raises(ValueError, match="Unknown subjects"):
        research_ledger.record(tree, {**HYPOTHESIS, "subjects": ["@NOPE@"]})
    with pytest.raises(ValueError, match="Unknown hypothesis_id"):
        research_ledger.record(tree, {**EVIDENCE, "hypothesis_id": "hyp_missing"})
    hid = research_ledger.record(tree, HYPOTHESIS)["hypothesis_id"]
    with pytest.raises(ValueError, match="needs recorded evidence"):
        research_ledger.record(tree, {**VERDICT, "hypothesis_id": hid})
    inconclusive = {**VERDICT, "hypothesis_id": hid, "status": "inconclusive"}
    assert research_ledger.record(tree, inconclusive)["status"] == "inconclusive"


def test_ledger_is_append_only_and_backed_up(tree):
    research_ledger.record(tree, HYPOTHESIS)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        tree.db.execute("UPDATE research_entries SET body='{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        tree.db.execute("DELETE FROM research_entries")
    tree.db.rollback()  # the refused statements opened an implicit transaction
    backup = tree.backup()
    with sqlite3.connect(backup["path"]) as copy:
        assert copy.execute("SELECT count(*) FROM research_entries").fetchone()[0] == 1
