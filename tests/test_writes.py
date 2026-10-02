"""Persistence, losslessness, failure boundaries, and current-read regressions."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gedcom_server import semantic, state
from gedcom_server.core import _get_individual, _search_individuals
from gedcom_server.document import Document
from gedcom_server.recovery import restore_backup
from gedcom_server.writes import INDEXES, TreeStore, projection, verify_backup

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


def note(text="Research note"):
    return {"op": "add_note", "record_id": "@I1@", "text": text}


def commit(tree, operations=None):
    proposal = tree.prepare(tree.revision, "Test sourced change", operations or [note()])
    return tree.apply(proposal["proposal_id"], tree.revision)


@pytest.mark.parametrize("newline,bom", [("\n", False), ("\r\n", False), ("\r\n", True)])
def test_lossless_roundtrip(newline, bom):
    raw = SAMPLE.read_text().replace("\n", newline).encode()
    raw = (b"\xef\xbb\xbf" if bom else b"") + raw
    assert Document(raw).bytes() == raw


def test_unknown_tags_survive_edit_and_export(tree):
    # A lossless editor preserves opaque tags and pointer notes verbatim.
    raw = tree.document(0).replace(
        b"1 SEX M\n", b"1 SEX M\n1 _CUSTOM original\n2 _NESTED opaque\n", 1
    )
    doc = Document(raw)
    doc.edit([note()])
    assert b"1 _CUSTOM original\n2 _NESTED opaque\n" in doc.bytes()
    assert doc.bytes().replace(b"1 NOTE Research note\n", b"", 1) == raw


def test_prepare_does_not_change_tree(tree):
    original = tree.document(0)
    preview = tree.prepare(0, "Research", [note()])
    assert "+1 NOTE Research note" in preview["diff"]
    assert tree.revision == 0
    assert tree.document(0) == original
    assert "Research note" not in _get_individual("@I1@")["notes"]


def test_apply_reads_baseline_and_idempotency(tree):
    baseline = tree.original.read_bytes()
    proposal = tree.prepare(0, "Research", [note()])
    first = tree.apply(proposal["proposal_id"], 0)
    retry = tree.apply(proposal["proposal_id"], 0)
    assert first["revision"] == retry["revision"] == 1
    assert retry["already_applied"]
    assert "Research note" in _get_individual("@I1@")["notes"]
    assert tree.original.read_bytes() == tree.baseline_path.read_bytes() == baseline
    assert tree.document(0) == baseline
    assert tree.export(1).read_bytes() == tree.document(1)
    assert verify_backup(Path(first["backup"]["path"]))["revision"] == 0


def test_stale_proposals_refused(tree):
    first = tree.prepare(0, "First", [note("A")])
    stale = tree.prepare(0, "Second", [note("B")])
    tree.apply(first["proposal_id"], 0)
    with pytest.raises(ValueError):
        tree.apply(stale["proposal_id"], 0)
    with pytest.raises(ValueError, match="Stale"):
        tree.prepare(0, "Stale", [note()])
    assert "B" not in _get_individual("@I1@")["notes"]


def test_backup_failure_aborts_write(tree, monkeypatch):
    proposal = tree.prepare(0, "Research", [note()])
    monkeypatch.setattr(tree, "backup", lambda: (_ for _ in ()).throw(OSError("Disk failed")))
    with pytest.raises(OSError):
        tree.apply(proposal["proposal_id"], 0)
    assert tree.latest()["id"] == tree.revision == 0
    assert "Research note" not in _get_individual("@I1@")["notes"]


def test_commit_failure_does_not_publish(tree):
    proposal = tree.prepare(0, "Research", [note()])
    tree.db.execute(
        "CREATE TRIGGER fail_commit BEFORE INSERT ON revisions BEGIN SELECT RAISE(ABORT,'disk failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        tree.apply(proposal["proposal_id"], 0)
    assert tree.latest()["id"] == tree.revision == 0
    assert "Research note" not in _get_individual("@I1@")["notes"]


def test_baseline_tampering_refuses_writes(tree):
    tree.original.write_bytes(tree.original.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="baseline"):
        tree.prepare(0, "Research", [note()])


def test_archive_tampering_refuses_startup(tree):
    tree.baseline_path.chmod(0o600)
    tree.baseline_path.write_bytes(b"tampered")
    tree.close()
    with pytest.raises(ValueError, match="Immutable"):
        TreeStore(tree.original, tree.directory)


def test_one_server_per_store(tree):
    with pytest.raises(ValueError, match="Another server"):
        TreeStore(tree.original, tree.directory)


def test_restart_recovers_committed_state(tree):
    commit(tree)
    tree.close()
    reopened = TreeStore(tree.original, tree.directory)
    try:
        assert reopened.revision == 1
        assert b"Research note" in reopened.document(1)
    finally:
        reopened.close()


def test_restore_preserves_history(tree):
    commit(tree)
    proposal = tree.prepare(1, "Undo research note", [], restore_revision=0)
    tree.apply(proposal["proposal_id"], 1)
    assert tree.revision == 2
    assert tree.document(2) == tree.document(0)
    assert b"Research note" in tree.document(1)
    assert "Research note" not in _get_individual("@I1@")["notes"]
    assert len(tree.history()) == 3
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        tree.db.execute("DELETE FROM revisions WHERE id=1")


def test_disaster_recovery_is_self_contained(tree, tmp_path):
    commit(tree)
    backup = Path(tree.backup()["path"])
    recovered = tmp_path / "recovered"
    result = restore_backup(backup, recovered)
    with pytest.raises(ValueError, match="already exist"):
        restore_backup(backup, recovered)
    other = TreeStore(Path(result["gedcom_file"]), recovered)
    try:
        assert other.document(0) == tree.document(0)
        assert other.document(1) == tree.document(1)
        assert other.history() == tree.history()
        rebuilt = projection(other.document(1), other.directory)
        assert rebuilt.individuals["@I1@"].notes == state.individuals["@I1@"].notes
        assert len(rebuilt.families) == len(state.families)
    finally:
        other.close()


def test_citation_and_event_reads(tree):
    commit(
        tree,
        [
            {
                "op": "add_event",
                "record_id": "@I1@",
                "tag": "RESI",
                "date": "1950",
                "place": "Boston, Massachusetts, USA",
                "source_id": "@S1@",
                "page": "42",
            }
        ],
    )
    event = state.individuals["@I1@"].events[-1]
    assert event.type == "RESI" and event.date == "1950"
    assert event.citations[0].source_title == "Massachusetts Vital Records"
    assert event.citations[0].page == "42"
    commit(
        tree,
        [
            {
                "op": "add_citation",
                "record_id": "@I1@",
                "path": [{"tag": "DEAT", "index": 0}],
                "source_id": "@S1@",
            }
        ],
    )
    death = next(event for event in state.individuals["@I1@"].events if event.type == "DEAT")
    assert death.citations[0].source_id == "@S1@"


def test_correct_field_and_indexes(tree):
    commit(
        tree,
        [
            {
                "op": "replace_value",
                "record_id": "@I1@",
                "path": [{"tag": "BIRT", "index": 0}, {"tag": "DATE", "index": 0}],
                "old_value": "15 MAR 1930",
                "value": "15 MAR 1931",
            }
        ],
    )
    assert state.individuals["@I1@"].birth_date == "15 MAR 1931"
    assert "@I1@" in state.birth_year_index[1931]
    assert "@I1@" not in state.birth_year_index[1930]
    assert len(_search_individuals("John")) > 0


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "add_note", "record_id": "@I1@", "text": "injected\x00control"},
        {"op": "add_event", "record_id": "@I1@", "tag": "BIRT", "source_id": "@missing@"},
        {
            "op": "replace_value",
            "record_id": "@I1@",
            "path": [{"tag": "NAME", "index": 0}],
            "old_value": "John /SMITH/",
            "value": "New /NAME/",
        },
        {
            "op": "replace_value",
            "record_id": "@I1@",
            "path": [{"tag": "FAMS", "index": 0}],
            "old_value": "@F1@",
            "value": "@F2@",
        },
        {"op": "add_note", "record_id": "@I1@", "text": "x", "unknown": True},
    ],
)
def test_invalid_operations_rejected(tree, operation):
    with pytest.raises(ValueError):
        tree.prepare(0, "Bad input", [operation])
    assert tree.revision == 0


def test_new_source_has_stable_unique_id(tree):
    first = tree.prepare(0, "Source", [{"op": "add_source", "title": "New archive"}])
    tree.apply(first["proposal_id"], 0)
    source_id = next(key for key in state.sources if key not in {"@S1@", "@S2@"})
    commit(tree, [{"op": "add_event", "record_id": "@I1@", "tag": "EVEN", "source_id": source_id}])
    assert state.individuals["@I1@"].events[-1].citations[0].source_title == "New archive"


def test_record_deduplication_and_retention(tree):
    initial_objects = tree.db.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    for index in range(8):
        commit(tree, [note(str(index))])
    assert tree.db.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == initial_objects + 8
    assert len(list((tree.directory / "backups").glob("*.sqlite"))) == 3
    assert len(list((tree.directory / "exports").glob("*.ged"))) == 1
    assert tree.db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    assert len(tree.history()) == 9


def test_capacity_guard(tree, monkeypatch):
    monkeypatch.setenv("GEDCOM_MAX_STORE_BYTES", "1")
    with pytest.raises(ValueError, match="size limit"):
        tree.prepare(0, "Research", [note()])


def test_corrupted_backup_detected(tree):
    path = Path(tree.backup()["path"])
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER immutable_object_update")
        db.execute("UPDATE objects SET digest='wrong' WHERE id=1")
    with pytest.raises(ValueError, match="checksum"):
        verify_backup(path)


def test_reads_remain_available_during_candidate_build(tree, monkeypatch):
    import gedcom_server.writes as writes

    proposal = tree.prepare(0, "Concurrent", [note()])
    real_projection = writes.projection
    building = threading.Event()
    resume = threading.Event()

    def delayed(data, directory):
        building.set()
        assert resume.wait(5)
        return real_projection(data, directory)

    monkeypatch.setattr(writes, "projection", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(tree.apply, proposal["proposal_id"], 0)
        assert building.wait(5)
        with state.TREE_LOCK:
            assert "Research note" not in _get_individual("@I1@")["notes"]
        resume.set()
        assert future.result(timeout=10)["revision"] == 1
    assert "Research note" in _get_individual("@I1@")["notes"]


def test_semantic_results_invalidated_on_write(tree, monkeypatch):
    monkeypatch.setattr(semantic, "_embeddings", object())
    commit(tree)
    assert semantic._embeddings is None


def test_simultaneous_retries_commit_once(tree, monkeypatch):
    import gedcom_server.writes as writes

    proposal = tree.prepare(0, "Concurrent retries", [note()])
    barrier = threading.Barrier(2)
    real_projection = writes.projection

    def together(data, directory):
        candidate = real_projection(data, directory)
        barrier.wait(timeout=5)
        return candidate

    monkeypatch.setattr(writes, "projection", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(tree.apply, proposal["proposal_id"], 0) for _ in range(2)]
        assert [job.result(timeout=10)["revision"] for job in jobs] == [1, 1]
    assert len(tree.history()) == 2


def test_background_semantic_rebuild_discards_obsolete_revision(tree, monkeypatch):
    import sys
    import time
    from types import SimpleNamespace

    import numpy as np

    started = threading.Event()
    resume = threading.Event()
    calls = []

    class Encoder:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            if len(calls) == 1:
                started.set()
                assert resume.wait(5)
            return np.ones((len(texts), 3), dtype=np.float32)

    monkeypatch.setattr(semantic, "_encoder", Encoder())
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=lambda name: Encoder()),
    )
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setattr(semantic, "_save_cache", lambda: None)
    commit(tree, [note("first version")])
    assert started.wait(5)
    commit(tree, [note("second version")])
    assert semantic._embeddings is None
    resume.set()
    deadline = time.monotonic() + 5
    while semantic._refresh_running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not semantic._refresh_running
    assert len(calls) == 2
    assert any("second version" in text for text in semantic._embedding_texts)


def test_unicode_note_separators_are_not_gedcom_line_breaks():
    raw = SAMPLE.read_bytes().replace(
        b"1 SEX M\n", "1 SEX M\n1 NOTE Before\u2028after\u0085end\n".encode(), 1
    )
    doc = Document(raw)
    assert doc.bytes() == raw
    doc.edit([note()])
    assert "Before\u2028after\u0085end".encode() in doc.bytes()


def test_post_commit_snapshot_contains_accepted_revision(tree):
    result = commit(tree)
    assert verify_backup(Path(result["current_backup"]["path"]))["revision"] == 1
    assert result["current_backup_error"] is None


def test_post_commit_backup_failure_reports_committed_revision(tree, monkeypatch):
    backup = tree.backup
    calls = 0

    def fail_second():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Independent snapshot unavailable")
        return backup()

    monkeypatch.setattr(tree, "backup", fail_second)
    result = commit(tree)
    assert result["revision"] == tree.revision == 1
    assert result["current_backup"] is None
    assert "unavailable" in result["current_backup_error"]
    assert "Research note" in _get_individual("@I1@")["notes"]


def test_live_snapshot_can_be_restored_without_writer_lock(tree, tmp_path):
    from gedcom_server.revision_storage import snapshot_database

    commit(tree)
    target = tmp_path / "snapshot-dir" / "snapshot.sqlite"
    result = snapshot_database(tree.directory / "tree.sqlite", target)
    assert result["revision"] == 1
    assert target.stat().st_mode & 0o777 == 0o400
    with pytest.raises(ValueError, match="already exists"):
        snapshot_database(tree.directory / "tree.sqlite", target)
    restored = restore_backup(target, tmp_path / "restored-snapshot")
    assert restored["revision"] == 1


def test_complete_diff_is_available_in_pages(tree):
    proposal = tree.prepare(0, "Many notes", [note(f"note {index}") for index in range(50)])
    offset = 0
    complete = []
    while True:
        page = tree.proposal_diff(proposal["proposal_id"], offset, limit=7)
        complete.extend(page["diff"].splitlines())
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert "\n".join(complete) == proposal["diff"]
    assert len(complete) == page["total_lines"]
    with pytest.raises(ValueError, match="nonnegative"):
        tree.proposal_diff(proposal["proposal_id"], -1)


def test_core_snapshot_identity_does_not_rehydrate_large_revision(tree, monkeypatch):
    from gedcom_server import writes
    from gedcom_server.interface_reads import get_people
    from gedcom_server.revision_storage import digest

    commit(tree)
    expected = digest(tree.document(tree.revision))
    monkeypatch.setattr(writes, "store", tree)

    def refuse_rehydration(revision):
        raise AssertionError("Core lookup reconstructed the whole revision")

    monkeypatch.setattr(tree, "document", refuse_rehydration)
    result = get_people(["I1"])
    assert result["snapshot"] == expected and result["revision"] == 1
    assert result["people"]["@I1@"]
    with pytest.raises(ValueError, match="Tree changed"):
        get_people(["I1"], expected_snapshot="stale")
