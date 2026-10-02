"""Complete record editing preserves evidence and the reviewed revision boundary."""

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from gedcom_server import semantic, state, writes
from gedcom_server.document import Document, LosslessEditor
from gedcom_server.field_edits import logical_text, subtree_hash
from gedcom_server.research_reads import get_record, get_source_references, list_records
from gedcom_server.tree_audit import error_signatures
from gedcom_server.writes import INDEXES, TreeStore, projection
from tests.test_mcp_transport import transport

SAMPLE = Path(__file__).parent / "fixtures" / "sample.ged"


def path(*tags):
    return [{"tag": tag, "index": 0} for tag in tags]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for key in (*INDEXES, "GEDCOM_FILE", "HOME_PERSON_ID"):
        monkeypatch.setattr(state, key, getattr(state, key))
    for key in ("_embeddings", "_embedding_ids", "_embedding_texts"):
        monkeypatch.setattr(semantic, key, getattr(semantic, key))
    raw = (
        SAMPLE.read_bytes()
        .replace(
            b"1 FAMC @F2@\n",
            b"1 FAMC @F2@\n2 PEDI birth\n2 STAT proven\n2 NOTE Link evidence\n"
            b"2 SOUR @S1@\n3 PAGE Relationship page\n2 _OPAQUE exact\n3 _CHILD retained\n",
            1,
        )
        .replace(
            b"0 TRLR\n",
            b"0 @R1@ REPO\n1 NAME Town Archive\n1 ADDR Main Street\n"
            b"0 @O1@ OBJE\n1 FILE photo.jpg\n2 FORM jpg\n"
            b"0 @N1@ NOTE Shared text\n1 CONT Second line\n0 _CUSTOM\n1 _VALUE original\n0 TRLR\n",
        )
    )
    baseline = tmp_path / "original.ged"
    baseline.write_bytes(raw)
    store = TreeStore(baseline, tmp_path / "store", "test-operator")
    store.publish(projection(raw, store.directory), store.export(0), 0)
    monkeypatch.setattr(writes, "store", store)
    yield store
    store.close()


def update(tree, record, tags, value, **extra):
    selected = path(*tags)
    doc = Document(tree.document(tree.revision))
    return {
        "op": "update_field",
        "record_id": record,
        "path": selected,
        "expected_sha256": subtree_hash(doc, doc.locate(record, selected)),
        "value": value,
        **extra,
    }


def remove(tree, record, tags):
    op = update(tree, record, tags, "")
    op.pop("value")
    op["op"] = "remove_field" if tags else "remove_record"
    if not tags:
        op.pop("path")
    return op


def commit(tree, *operations):
    before = tree.document(tree.revision)
    revision = tree.revision
    proposal = tree.prepare(revision, "Review evidence correction", list(operations))
    assert tree.revision == revision and tree.document(revision) == before
    tree.apply(proposal["proposal_id"], revision)
    return proposal


def test_missing_fields_and_clear_values_publish_current_reads(tree):
    commit(
        tree,
        {"op": "add_individual", "individual_id": "@NEW@", "name": "New /Person/"},
        {"op": "add_field", "record_id": "@NEW@", "field": {"tag": "SEX", "value": "U"}},
        {
            "op": "add_field",
            "record_id": "@I3@",
            "path": path("OCCU"),
            "field": {"tag": "PLAC", "value": "Boston"},
        },
    )
    assert state.individuals["@NEW@"].sex == "U"
    assert state.individuals["@I3@"].events[1].place == "Boston"
    commit(tree, update(tree, "@I3@", ["OCCU", "DATE"], ""))
    assert not state.individuals["@I3@"].events[1].date
    commit(tree, remove(tree, "@I3@", ["OCCU", "DATE"]))
    commit(
        tree,
        {
            "op": "add_field",
            "record_id": "@I3@",
            "path": path("OCCU"),
            "field": {"tag": "DATE", "value": "ABT 1980"},
        },
    )
    assert state.individuals["@I3@"].events[1].date == "ABOUT 1980"


def test_place_and_event_updates_preserve_nested_evidence(tree):
    commit(
        tree,
        {
            "op": "add_field",
            "record_id": "@I1@",
            "path": path("BIRT", "PLAC"),
            "field": {
                "tag": "MAP",
                "children": [
                    {"tag": "LATI", "value": "N42.36"},
                    {"tag": "LONG", "value": "W71.06"},
                ],
            },
        },
    )
    commit(
        tree,
        update(tree, "@I1@", ["BIRT", "PLAC"], "Boston, Massachusetts, USA"),
        update(tree, "@I3@", ["OCCU"], "Software Engineer", tag="EVEN"),
    )
    raw = tree.document(tree.revision)
    assert b"3 MAP\n4 LATI N42.36\n4 LONG W71.06\n" in raw
    event = state.individuals["@I3@"].events[1]
    assert event.type == "EVEN" and event.description == "Software Engineer"
    assert event.notes == ["Software Engineer"] and event.date == "FROM 1980 TO 2020"
    commit(tree, remove(tree, "@I3@", ["EVEN"]))
    assert all(e.type != "EVEN" for e in state.individuals["@I3@"].events)


def test_alternate_names_components_and_occurrence_order(tree):
    commit(
        tree,
        {
            "op": "add_field",
            "record_id": "@I1@",
            "index": 1,
            "field": {
                "tag": "NAME",
                "value": "Jack /Smith/",
                "children": [
                    {"tag": "GIVN", "value": "Jack"},
                    {"tag": "SURN", "value": "Smith"},
                    {"tag": "NICK", "value": "Jackie"},
                    {"tag": "TYPE", "value": "alias"},
                ],
            },
        },
    )
    alternate = [{"tag": "NAME", "index": 1}]
    selected = get_record("I1", alternate)["items"][0]
    commit(
        tree,
        {
            "op": "update_name",
            "individual_id": "@I1@",
            "name_index": 1,
            "old_name": "Jack /Smith/",
            "name": "Jackson /Smith/",
            "given_name": "Jackson",
            "surname": "Smith",
        },
    )
    assert state.individuals["@I1@"].given_name == "John"
    assert "2 NICK Jackie" in get_record("I1", alternate)["raw"]
    with pytest.raises(ValueError, match="Subtree changed"):
        tree.prepare(
            tree.revision,
            "Stale alternate",
            [
                {
                    "op": "remove_field",
                    "record_id": "@I1@",
                    "path": alternate,
                    "expected_sha256": selected["subtree_sha256"],
                }
            ],
        )
    selected = get_record("I1", alternate)["items"][0]
    commit(
        tree,
        {
            "op": "remove_field",
            "record_id": "@I1@",
            "path": alternate,
            "expected_sha256": selected["subtree_sha256"],
        },
    )
    assert b"Jackson" not in tree.document(tree.revision)


@pytest.mark.parametrize("newline,bom", [(b"\n", False), (b"\r\n", True)])
def test_multiline_unicode_is_lossless_and_cannot_inject_records(newline, bom, tmp_path):
    raw = SAMPLE.read_bytes().replace(b"\n", newline)
    raw = (b"\xef\xbb\xbf" if bom else b"") + raw
    text = "é🧬 " * 150 + "\n\n0 @FAKE@ INDI\nlast line\n"
    result = LosslessEditor().apply(raw, [{"op": "add_note", "record_id": "@I1@", "text": text}])
    doc = Document(result.data)
    selected = doc.locate("@I1@", path("NOTE"))
    assert logical_text(doc, selected) == text
    assert all(line.xref != "@FAKE@" for line in doc.lines)
    assert doc.bytes().startswith(b"\xef\xbb\xbf") == bom
    note = "".join(line.raw for line in doc.lines[selected : doc.end(selected)]).encode()
    assert result.data.replace(note, b"", 1) == raw
    target = projection(result.data, tmp_path)
    assert target.individuals["@I1@"].notes == [text]
    assert all(len(line.value.encode()) <= 200 for line in doc.lines[selected : doc.end(selected)])


def test_note_edit_remove_and_shared_note_root(tree):
    commit(
        tree,
        {
            "op": "add_note",
            "record_id": "@I1@",
            "path": path("BIRT"),
            "text": "Original\ntranscription",
        },
        {"op": "add_note", "record_id": "@S1@", "text": "Source context"},
    )
    commit(
        tree,
        {
            "op": "add_citation",
            "record_id": "@I1@",
            "path": path("BIRT", "NOTE"),
            "source_id": "@S2@",
        },
    )
    commit(
        tree,
        update(tree, "@I1@", ["BIRT", "NOTE"], "Revised\ntranscription"),
        update(tree, "@N1@", [], "Shared corrected\nsecond line"),
    )
    note = get_record("I1", path("BIRT", "NOTE"))
    assert note["items"][0]["text"] == "Revised\ntranscription"
    assert "3 SOUR @S2@" in note["raw"]
    assert get_record("N1")["items"][0]["text"] == "Shared corrected\nsecond line"
    commit(tree, remove(tree, "@I1@", ["BIRT", "NOTE"]))
    assert not state.individuals["@I1@"].events[0].notes


def test_new_repository_source_and_citation_are_atomic(tree):
    quote = "Evidence " * 70 + "\nSecond paragraph"
    commit(
        tree,
        {
            "op": "add_record",
            "record_id": "@R2@",
            "tag": "REPO",
            "fields": [{"tag": "NAME", "value": "New Archive"}],
        },
        {
            "op": "add_source",
            "source_id": "@SNEW@",
            "title": "New Register",
            "author": "Archive Staff",
            "publication": "Digitized edition",
            "repository_id": "@R2@",
            "note": "First line\nSecond line",
        },
        {
            "op": "add_citation",
            "record_id": "@I1@",
            "path": path("BIRT"),
            "source_id": "@SNEW@",
            "page": "42",
            "text": quote,
            "url": "https://example.org/42",
        },
        {"op": "add_citation", "record_id": "@I1@", "path": path("NAME"), "source_id": "@SNEW@"},
    )
    citation = state.individuals["@I1@"].events[0].citations[-1]
    assert citation.source_title == "New Register" and citation.text == quote
    assert citation.url == "https://example.org/42"
    assert state.sources["@SNEW@"].repository_id == "@R2@"
    commit(
        tree,
        update(tree, "@SNEW@", ["TITL"], "Corrected Register"),
        update(tree, "@R2@", ["NAME"], "Corrected Archive"),
        update(tree, "@I1@", ["BIRT", "SOUR", "PAGE"], "43"),
    )
    assert state.sources["@SNEW@"].title == "Corrected Register"
    assert state.individuals["@I1@"].events[0].citations[0].page == "43"
    assert state.individuals["@I1@"].events[0].citations[-1].source_title == "Corrected Register"


def test_citation_retarget_and_source_delete_require_explicit_reference_cleanup(tree):
    commit(tree, {"op": "add_source", "source_id": "@SNEW@", "title": "Better evidence"})
    commit(tree, update(tree, "@I1@", ["BIRT", "SOUR"], "@SNEW@"))
    assert state.individuals["@I1@"].events[0].citations[0].page == "Page 42"
    before = tree.document(tree.revision)
    with pytest.raises(ValueError, match="integrity"):
        tree.prepare(tree.revision, "Referenced source", [remove(tree, "@S1@", [])])
    assert tree.document(tree.revision) == before
    refs = get_source_references("S1")["items"]
    ops = []
    for ref in refs:
        field = get_record(ref["record_id"], ref["path"])["items"][0]
        ops.append(
            {
                "op": "remove_field",
                "record_id": ref["record_id"],
                "path": ref["path"],
                "expected_sha256": field["subtree_sha256"],
            }
        )
    commit(tree, *ops, remove(tree, "@S1@", []))
    assert "@S1@" not in state.sources


def test_reverse_citations_enable_header_and_anonymous_source_cleanup(tree):
    original_header = get_record("HEAD")["raw"]
    original_anonymous = get_record("anonymous-_CUSTOM-0")["raw"]
    commit(
        tree,
        {"op": "add_source", "source_id": "@SNEW@", "title": "Auxiliary evidence"},
        *[
            {
                "op": "add_citation",
                "record_id": record,
                "path": selected,
                "source_id": "@SNEW@",
                "page": "Auxiliary page",
            }
            for record, selected in [("HEAD", []), ("anonymous-_CUSTOM-0", path("_VALUE"))]
        ],
    )
    revision = tree.revision
    before = tree.document(revision)
    with pytest.raises(ValueError, match="integrity"):
        tree.prepare(revision, "Referenced source", [remove(tree, "@SNEW@", [])])
    assert tree.revision == revision and tree.document(revision) == before
    refs = get_source_references("SNEW")
    assert refs["revision"] == revision and refs["total"] == 2
    assert [r["record_id"] for r in refs["items"]] == ["HEAD", "anonymous-_CUSTOM-0"]
    operations = [
        {
            "op": "remove_field",
            "record_id": ref["record_id"],
            "path": ref["path"],
            "expected_sha256": get_record(ref["record_id"], ref["path"])["items"][0][
                "subtree_sha256"
            ],
        }
        for ref in refs["items"]
    ]
    commit(tree, *operations, remove(tree, "@SNEW@", []))
    assert "@SNEW@" not in state.sources
    assert b"@SNEW@" not in tree.document(tree.revision)
    assert get_record("anonymous-_CUSTOM-0")["raw"] == original_anonymous
    assert get_record("HEAD")["raw"] == original_header


def test_relationship_qualifier_update_retains_all_evidence(tree):
    link = get_record("I5", path("FAMC"))["items"][0]
    proposal = commit(
        tree,
        {
            "op": "update_relationship",
            "family_id": "@F2@",
            "individual_id": "@I5@",
            "role": "CHIL",
            "expected_sha256": link["subtree_sha256"],
            "pedigree": "adopted",
            "status": None,
        },
    )
    assert proposal["review"]["force_operation_indexes"] == []
    raw = get_record("I5", path("FAMC"))["raw"]
    assert "2 PEDI adopted" in raw and "2 STAT" not in raw
    assert "Link evidence" in raw and "Relationship page" in raw and "3 _CHILD retained" in raw
    assert state.individuals["@I5@"].parent_families[0].pedigree == "adopted"


def test_auxiliary_inventory_media_custom_fields_and_header_metadata(tree):
    records = []
    offset = 0
    while offset is not None:
        page = list_records(offset=offset, limit=3)
        records.extend(page["items"])
        offset = page["next_offset"]
    assert {"HEAD", "TRLR", "@N1@", "@R1@", "@O1@", "anonymous-_CUSTOM-0"} <= {
        item["record_id"] for item in records
    }
    assert list_records("OBJE")["items"] == [{"record_id": "@O1@", "record_type": "OBJE"}]
    commit(
        tree,
        update(tree, "@O1@", ["FILE"], "corrected.jpg"),
        update(tree, "anonymous-_CUSTOM-0", ["_VALUE"], "corrected"),
        update(tree, "HEAD", ["SOUR", "VERS"], "2.0"),
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "_UID", "value": "external-id"}},
    )
    assert "2 FORM jpg" in get_record("O1")["raw"]
    assert "1 _VALUE corrected" in get_record("anonymous-_CUSTOM-0")["raw"]
    assert "2 VERS 2.0" in get_record("HEAD")["raw"]
    assert get_record("TRLR")["items"][0]["tag"] == "TRLR"
    assert not error_signatures(Document(tree.document(tree.revision)))


def test_explicit_subtree_replacement_and_hash_guards(tree):
    old = get_record("I1", path("BIRT"))["items"][0]
    replacement = {
        "op": "replace_field",
        "record_id": "@I1@",
        "path": path("BIRT"),
        "expected_sha256": old["subtree_sha256"],
        "field": {
            "tag": "BIRT",
            "children": [{"tag": "DATE", "value": "ABT 1931"}, {"tag": "SOUR", "value": "@S2@"}],
        },
    }
    proposal = commit(tree, replacement)
    assert "-2 PLAC Boston" in proposal["diff"] and "+2 DATE ABT 1931" in proposal["diff"]
    assert state.individuals["@I1@"].birth_date == "ABOUT 1931"
    assert state.individuals["@I1@"].birth_place is None
    with pytest.raises(ValueError, match="Subtree changed"):
        tree.prepare(tree.revision, "Stale subtree", [replacement])


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "_BAD\n0", "value": "x"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "SOUR", "value": "@R1@"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "NOTE", "value": "@MISSING@"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "OBJE", "value": "@S1@"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "SEX", "value": "x\x00"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "SEX", "value": "X"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "FAMC", "value": "F2"}},
        {"op": "add_record", "record_id": "@O1@", "tag": "OBJE"},
        {"op": "add_record", "record_id": "@NEW@", "tag": "HEAD"},
    ],
)
def test_invalid_generic_edits_do_not_persist_proposals(tree, bad):
    before = tree.document(0)
    with pytest.raises(ValueError):
        tree.prepare(0, "Invalid edit", [bad])
    assert tree.revision == 0 and tree.document(0) == before
    assert tree.db.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0


def test_graph_and_name_edits_cannot_bypass_integrity(tree):
    for op in [
        update(tree, "@I5@", ["FAMC"], "@F1@"),
        update(tree, "@I1@", ["NAME"], "John /Other/"),
        update(tree, "HEAD", ["CHAR"], "ASCII"),
    ]:
        with pytest.raises(ValueError):
            tree.prepare(0, "Invalid correction", [op])
    commit(
        tree,
        remove(tree, "@F2@", ["CHIL"]),
        {"op": "add_field", "record_id": "@F1@", "field": {"tag": "CHIL", "value": "@I5@"}},
        update(tree, "@I5@", ["FAMC"], "@F1@"),
    )
    assert "@I5@" in state.families["@F1@"].children_ids
    assert "Link evidence" in get_record("I5", path("FAMC"))["raw"]


def test_duplicate_citations_are_removed_in_reverse_occurrence_order(tree):
    commit(
        tree,
        {
            "op": "add_citation",
            "record_id": "@I1@",
            "path": path("BIRT"),
            "source_id": "@S2@",
            "page": "Different evidence",
        },
    )
    fields = [
        get_record("I1", path("BIRT") + [{"tag": "SOUR", "index": i}])["items"][0] for i in range(2)
    ]
    operations = [
        {
            "op": "remove_field",
            "record_id": "@I1@",
            "path": field["path"],
            "expected_sha256": field["subtree_sha256"],
        }
        for field in fields
    ]
    with pytest.raises(ValueError):
        tree.prepare(tree.revision, "Shifted occurrences", operations)
    commit(tree, *reversed(operations))
    assert not state.individuals["@I1@"].events[0].citations


def test_text_limits_and_bounded_read_previews(tree):
    long_text = "🧬" * 700 + "\nTail"
    commit(tree, {"op": "add_note", "record_id": "@I1@", "text": long_text})
    first = get_record("I1", path("NOTE"), limit=1)
    assert first["items"][0]["text_truncated"]
    assert len(first["items"][0]["text"].encode()) <= 2000
    assert first["next_offset"] is not None
    for text in ["x" * (1024 * 1024 + 1), "Forbidden\x00text"]:
        with pytest.raises(ValueError):
            tree.prepare(
                tree.revision,
                "Invalid text",
                [{"op": "add_note", "record_id": "@I1@", "text": text}],
            )


def test_generic_graph_operations_refuse_ancestry_cycles(tree):
    operations = [
        {
            "op": "add_record",
            "record_id": "@CYCLE@",
            "tag": "FAM",
            "fields": [{"tag": "HUSB", "value": "@I5@"}, {"tag": "CHIL", "value": "@I1@"}],
        },
        {"op": "add_field", "record_id": "@I5@", "field": {"tag": "FAMS", "value": "@CYCLE@"}},
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "FAMC", "value": "@CYCLE@"}},
    ]
    with pytest.raises(ValueError, match="ancestry_cycle"):
        tree.prepare(0, "Refuse cyclic ancestry", operations)
    assert tree.revision == 0 and "@CYCLE@" not in state.families


@pytest.mark.parametrize("record", ["HEAD", "TRLR", "@I1@", "@F1@"])
def test_generic_record_deletion_cannot_bypass_envelope_or_graph_deletion(tree, record):
    with pytest.raises(ValueError, match="person/family deletion"):
        tree.prepare(0, "Protected record type", [remove(tree, record, [])])


def test_nested_operation_schemas_are_strict(tree):
    for operation in [
        {"op": "add_field", "record_id": "@I1@", "field": {"tag": "NOTE", "typo": "text"}},
        {
            "op": "add_field",
            "record_id": "@I1@",
            "index": True,
            "field": {"tag": "NOTE", "value": "x"},
        },
        {"op": "add_source", "source_id": "", "title": "No silent ID substitution"},
    ]:
        with pytest.raises(ValueError):
            tree.prepare(0, "Invalid schema", [operation])


def test_full_editing_discovery_apply_restore_and_restart_over_mcp(tmp_path):
    async def exercise():
        directory = tmp_path / "store"
        async with Client(transport(directory), timeout=20) as client:
            definitions = (
                await client.call_tool("search_tools", {"category": "changes", "limit": 10})
            ).data
            schema = next(
                t["inputSchema"]
                for t in definitions["tools"]
                if t["execution"]["operation"] == "edit_records"
            )
            assert "FieldNode" in str(schema) and "update_relationship" in str(schema)
            records = (
                await client.call_tool(
                    "call_research_tool",
                    {"name": "list_records", "arguments": {"record_type": "SOUR"}},
                )
            ).data
            assert records["total"] == 2
            field = (await client.call_tool("get_record", {"record_id": "S1"})).data["items"][1]
            note_text = "Research " * 50 + "\nSecond line\n0 @FAKE@ INDI"
            operations = [
                {
                    "op": "update_field",
                    "record_id": "@S1@",
                    "path": field["path"],
                    "expected_sha256": field["subtree_sha256"],
                    "value": "Corrected source",
                },
                {"op": "add_note", "record_id": "@I1@", "path": path("BIRT"), "text": note_text},
                {"op": "add_source", "source_id": "@NEWS@", "title": "New source"},
                {
                    "op": "add_citation",
                    "record_id": "@I1@",
                    "path": path("NAME"),
                    "source_id": "@NEWS@",
                },
            ]
            proposal = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "edit_records",
                        "arguments": {
                            "expected_revision": 0,
                            "reason": "Correct evidence",
                            "operations": operations,
                        },
                    },
                )
            ).data
            assert (await client.call_tool("get_tree_context", {})).data["revision"] == 0
            await client.call_tool(
                "apply_tree_change",
                {"proposal_id": proposal["proposal_id"], "expected_revision": 0},
            )
            source = (
                await client.call_tool(
                    "call_research_tool", {"name": "get_source", "arguments": {"source_id": "S1"}}
                )
            ).data
            assert source["title"] == "Corrected source"
            note = (
                await client.call_tool(
                    "get_record", {"record_id": "I1", "path": path("BIRT", "NOTE")}
                )
            ).data
            assert note["items"][0]["text"] == note_text
            assert (
                note["items"][0]["subtree_sha256"]
                == hashlib.sha256(note["raw"].encode()).hexdigest()
            )
            with pytest.raises(ToolError):
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "edit_records",
                        "arguments": {
                            "expected_revision": 1,
                            "reason": "Stale hash",
                            "operations": [operations[0]],
                        },
                    },
                )
        async with Client(transport(directory), timeout=20) as client:
            assert (await client.call_tool("get_tree_context", {})).data["revision"] == 1
            restored = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "restore",
                        "arguments": {
                            "expected_revision": 1,
                            "restore_revision": 0,
                            "reason": "Restore reviewed baseline",
                        },
                    },
                )
            ).data
            await client.call_tool(
                "apply_tree_change",
                {"proposal_id": restored["proposal_id"], "expected_revision": 1},
            )
            export = (
                await client.call_tool("maintain_tree", {"action": "export", "revision": 2})
            ).data
            assert Path(export["path"]).read_bytes() == SAMPLE.read_bytes()

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))
