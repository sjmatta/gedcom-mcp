"""Structural editing, prune boundaries, evidence retention and whole-tree checks."""

import asyncio
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from gedcom_server import semantic, state
from gedcom_server.document import Document, LosslessEditor
from gedcom_server.pruning import plan_document
from gedcom_server.tree_audit import TreeIndex, audit_document
from gedcom_server.writes import INDEXES, TreeStore, projection

SAMPLE = Path(__file__).parent / "fixtures" / "sample.ged"


def data(records):
    return ("0 HEAD\n1 CHAR UTF-8\n" + records + "0 TRLR\n").encode()


def edit(raw, *operations):
    return LosslessEditor().apply(raw, list(operations)).data


def operation(op, **kwargs):
    return {"op": op, **kwargs}


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


def test_relationship_replacement_is_reciprocal_and_preserves_other_families(tree):
    original = tree.document(0)
    proposal = tree.prepare(
        0,
        "Correct child family with adoption evidence",
        [
            operation("remove_relationship", family_id="@F2@", individual_id="@I5@", role="CHIL"),
            operation(
                "add_relationship",
                family_id="@F1@",
                individual_id="@I5@",
                role="CHIL",
                pedigree="adopted",
                status="challenged",
            ),
        ],
    )
    assert tree.revision == 0 and tree.document(0) == original
    assert set(proposal["affected_records"]) == {"@F1@", "@F2@", "@I5@"}
    tree.apply(proposal["proposal_id"], 0)
    assert "@I5@" not in state.families["@F2@"].children_ids
    assert "@I5@" in state.families["@F1@"].children_ids
    raw = tree.document(1)
    assert b"1 FAMC @F1@\n2 PEDI adopted\n2 STAT challenged" in raw
    assert not audit_document(Document(raw))["summary"].get("error")
    undo = tree.prepare(1, "Undo relationship correction", [], 0)
    tree.apply(undo["proposal_id"], 1)
    assert tree.document(2) == original


def test_create_person_with_family_and_sourced_event_is_atomic(tree):
    original = tree.document(0)
    proposal = tree.prepare(
        0,
        "Add reviewed person and evidence",
        [
            operation("add_individual", individual_id="@INEW@", name="Zoë /Example/", sex="U"),
            operation("add_relationship", family_id="@F1@", individual_id="@INEW@", role="CHIL"),
            operation(
                "add_event", record_id="@INEW@", tag="BIRT", source_id="@S1@", date="ABT 1900"
            ),
        ],
    )
    assert tree.revision == 0 and tree.document(0) == original
    assert "@INEW@" not in state.individuals
    result = tree.apply(proposal["proposal_id"], 0)
    assert result["revision"] == 1
    assert "@INEW@" in state.individuals
    assert "@INEW@" in state.families["@F1@"].children_ids
    assert b"1 FAMC @F1@" in tree.document(1)
    assert b"2 DATE ABT 1900" in tree.document(1)
    assert tree.original.read_bytes() == original
    assert tree.apply(proposal["proposal_id"], 0)["already_applied"]
    undo = tree.prepare(1, "Restore before creation", [], 0)
    tree.apply(undo["proposal_id"], 1)
    assert tree.document(2) == original


@pytest.mark.parametrize(
    "fields",
    [
        {"individual_id": "@I1@", "name": "Duplicate"},
        {"individual_id": "@F1@", "name": "Wrong record collision"},
        {"individual_id": "missing-delimiters", "name": "Invalid ID"},
        {"individual_id": "@I\x00@", "name": "Invalid ID"},
        {"name": "Missing ID"},
        {"individual_id": "@NEW@", "name": ""},
        {"individual_id": "@NEW@", "name": "Injected\n0 @X@ INDI"},
        {"individual_id": "@NEW@", "name": "Jane /Broken"},
        {"individual_id": "@NEW@", "name": "@I1@"},
        {"individual_id": "@NEW@", "name": "é" * 101},
        {"individual_id": "@NEW@", "name": "Jane", "sex": "X"},
        {"individual_id": "@NEW@", "name": "Jane", "sex": []},
        {"individual_id": "@NEW@", "name": "Jane", "note": "Bad\nNote"},
        {"individual_id": "@NEW@", "name": "Jane", "birth_date": "1900"},
    ],
)
def test_create_person_refuses_invalid_inputs(fields):
    with pytest.raises(ValueError):
        edit(SAMPLE.read_bytes(), operation("add_individual", **fields))


@pytest.mark.parametrize("newline,bom", [(b"\n", b""), (b"\r\n", b"\xef\xbb\xbf")])
def test_create_person_preserves_existing_bytes(newline, bom):
    raw = bom + SAMPLE.read_bytes().replace(b"\n", newline)
    result = edit(raw, operation("add_individual", individual_id="@NEW@", name="Mononym"))
    block = b"0 @NEW@ INDI" + newline + b"1 NAME Mononym" + newline
    assert result.replace(block, b"", 1) == raw


def test_failed_creation_batch_leaves_store_unchanged(tree):
    original = tree.document(0)
    with pytest.raises(ValueError):
        tree.prepare(
            0,
            "Invalid link",
            [
                operation("add_individual", individual_id="@NEW@", name="Jane"),
                operation(
                    "add_relationship", individual_id="@NEW@", family_id="@missing@", role="CHIL"
                ),
            ],
        )
    assert tree.revision == 0 and tree.document(0) == original
    assert "@NEW@" not in state.individuals


def test_update_name_preserves_evidence_alternates_and_current_reads(tree):
    original = tree.document(0)
    proposal = tree.prepare(
        0,
        "Correct spelling",
        [
            operation(
                "update_name",
                individual_id="@I1@",
                old_name="John /SMITH/",
                name="Jonathan /Smith/",
                given_name="Jonathan",
                surname="Smith",
            )
        ],
    )
    assert state.individuals["@I1@"].given_name == "John"
    tree.apply(proposal["proposal_id"], 0)
    assert state.individuals["@I1@"].given_name == "Jonathan"
    assert state.individuals["@I1@"].surname == "Smith"
    assert tree.document(1) == original.replace(b"John /SMITH/", b"Jonathan /Smith/", 1).replace(
        b"2 GIVN John\n2 SURN SMITH", b"2 GIVN Jonathan\n2 SURN Smith", 1
    )


def test_update_name_keeps_nested_name_evidence_and_other_name_occurrences():
    raw = data(
        "0 @I@ INDI\n1 NAME Old /Surname/\n2 GIVN Old\n3 _PROOF keep\n2 SURN Surname\n"
        "2 NICK Nick\n2 SOUR @S@\n3 PAGE 12\n2 _CUSTOM opaque\n"
        "1 NAME Alternate /Surname/\n2 TYPE aka\n0 @S@ SOUR\n1 TITL Record\n"
    )
    result = edit(
        raw,
        operation(
            "update_name",
            individual_id="@I@",
            old_name="Old /Surname/",
            name="New /Corrected/",
            given_name="New",
            surname="Corrected",
        ),
    )
    assert result == raw.replace(b"Old /Surname/", b"New /Corrected/", 1).replace(
        b"2 GIVN Old", b"2 GIVN New", 1
    ).replace(b"2 SURN Surname", b"2 SURN Corrected", 1)
    # An alternate name can be corrected independently, adding missing structured fields.
    alternate = edit(
        raw,
        operation(
            "update_name",
            individual_id="@I@",
            name_index=1,
            old_name="Alternate /Surname/",
            name="Alias /Surname/",
            given_name="Alias",
            surname="Surname",
        ),
    )
    assert b"1 NAME Old /Surname/" in alternate
    assert b"1 NAME Alias /Surname/\n2 TYPE aka\n2 GIVN Alias\n2 SURN Surname" in alternate


@pytest.mark.parametrize(
    "overrides",
    [
        {"old_name": "Stale /SMITH/"},
        {"name_index": -1},
        {"name_index": True},
        {"name_index": 1},
        {"name": "Bad\nname"},
        {"surname": "Mismatch"},
        {"given_name": "Bad/name"},
        {"individual_id": "@F1@"},
    ],
)
def test_update_name_refuses_stale_or_invalid_inputs(overrides):
    fields = {
        "individual_id": "@I1@",
        "old_name": "John /SMITH/",
        "name": "Jane /Smith/",
        "given_name": "Jane",
        "surname": "Smith",
    }
    fields.update(overrides)
    with pytest.raises(ValueError):
        edit(SAMPLE.read_bytes(), operation("update_name", **fields))


def test_relationship_changes_refuse_cycles_and_invalid_partner_roles():
    raw = SAMPLE.read_bytes()
    with pytest.raises(ValueError, match="integrity"):
        edit(
            raw, operation("add_relationship", family_id="@F2@", individual_id="@I1@", role="CHIL")
        )
    with pytest.raises(ValueError, match="occupied"):
        edit(
            raw, operation("add_relationship", family_id="@F1@", individual_id="@I6@", role="HUSB")
        )
    with pytest.raises(ValueError, match="different role"):
        edit(
            raw, operation("add_relationship", family_id="@F1@", individual_id="@I1@", role="CHIL")
        )


def test_relationship_evidence_needs_force_and_is_visible():
    raw = SAMPLE.read_bytes().replace(
        b"1 FAMC @F2@\n", b"1 FAMC @F2@\n2 NOTE Adopted per letter\n", 1
    )
    op = operation("remove_relationship", family_id="@F2@", individual_id="@I5@", role="CHIL")
    with pytest.raises(ValueError, match="force"):
        edit(raw, op)
    result = edit(raw, dict(op, force=True))
    assert "Adopted per letter" in "\n".join(LosslessEditor().diff(raw, result, ["@I5@", "@F2@"]))


@pytest.mark.parametrize("force", [False, True])
def test_merge_preserves_evidence_redirects_opaque_pointers_and_coalesces_links(force):
    raw = data(
        "0 @I1@ INDI\n1 NAME Alice /Example/\n1 FAMS @F1@\n1 NOTE First evidence\n"
        "0 @I2@ INDI\n1 NAME Alice /Example/\n1 FAMS @F1@\n1 NOTE Second evidence\n2 CONT Continued evidence\n"
        "0 @I3@ INDI\n1 _LINK @I2@\n"
        "0 @F1@ FAM\n1 HUSB @I1@\n1 HUSB @I2@\n"
    )
    result = edit(
        raw,
        operation(
            "merge_individuals",
            source_id="@I2@",
            target_id="@I1@",
            identity_evidence="Same independently verified archive identifier",
            force=force,
        ),
    )
    assert b"0 @I2@" not in result
    assert b"1 _LINK @I1@" in result
    assert b"1 NOTE Second evidence\n2 CONT Continued evidence" in result
    assert b"1 NOTE First evidence" in result
    assert result.count(b"1 FAMS @F1@") == 1
    assert result.count(b"1 HUSB @I1@") == 1
    assert not audit_document(Document(result))["summary"].get("error")


def test_merge_conflicts_retained_only_with_review_override():
    raw = data(
        "0 @I1@ INDI\n1 NAME A /Example/\n1 BIRT\n2 DATE 1900\n2 SOUR @S1@\n"
        "0 @I2@ INDI\n1 NAME B /Example/\n1 BIRT\n2 DATE 1901\n2 SOUR @S2@\n"
        "0 @S1@ SOUR\n1 TITL First\n0 @S2@ SOUR\n1 TITL Second\n"
    )
    op = operation(
        "merge_individuals",
        source_id="@I2@",
        target_id="@I1@",
        identity_evidence="Archive correction explicitly identifies both records",
    )
    with pytest.raises(ValueError, match="force=true"):
        edit(raw, op)
    result = edit(raw, dict(op, force=True))
    assert b"2 DATE 1900" in result and b"2 DATE 1901" in result
    assert b"2 SOUR @S1@" in result and b"2 SOUR @S2@" in result
    assert audit_document(Document(result))["issue_counts"]["conflicting_facts"] == 1


def test_merge_cannot_create_self_parent_even_with_force():
    raw = SAMPLE.read_bytes()
    with pytest.raises(ValueError, match="integrity"):
        edit(
            raw,
            operation(
                "merge_individuals",
                source_id="@I3@",
                target_id="@I1@",
                identity_evidence="Reviewed identity",
                force=True,
            ),
        )


def test_merge_qualifier_conflicts_are_never_silently_discarded():
    raw = data(
        "0 @I1@ INDI\n1 FAMC @F1@\n2 PEDI birth\n"
        "0 @I2@ INDI\n1 FAMC @F1@\n2 PEDI adopted\n"
        "0 @F1@ FAM\n1 CHIL @I1@\n1 CHIL @I2@\n"
    )
    with pytest.raises(ValueError, match="qualifiers"):
        edit(
            raw,
            operation(
                "merge_individuals",
                source_id="@I2@",
                target_id="@I1@",
                identity_evidence="Reviewed identity",
                force=True,
            ),
        )


def test_deletion_updates_family_and_force_removes_nested_external_references_in_diff():
    raw = (
        SAMPLE.read_bytes()
        .replace(b"1 CHAR UTF-8\n", b"1 CHAR UTF-8\n1 _ROOT @I6@\n")
        .replace(b"0 @S1@ SOUR\n", b"0 @S1@ SOUR\n1 NOTE @I6@\n2 _LINK @I6@\n")
    )
    with pytest.raises(ValueError, match="reference"):
        edit(raw, operation("delete_individual", individual_id="@I6@"))
    result = edit(raw, operation("delete_individual", individual_id="@I6@", force=True))
    assert b"@I6@" not in result
    diff = "\n".join(LosslessEditor().diff(raw, result, ["@I6@", "@F2@", "@S1@"]))
    assert "-1 _ROOT @I6@" in diff and "-1 NOTE @I6@" in diff
    assert not audit_document(Document(result))["summary"].get("error")


def test_only_empty_unreferenced_families_can_be_deleted_without_force():
    raw = data("0 @I1@ INDI\n0 @F1@ FAM\n0 @F2@ FAM\n1 NOTE Keep evidence\n")
    result = edit(raw, operation("delete_family", family_id="@F1@"))
    with pytest.raises(ValueError, match="force"):
        edit(result, operation("delete_family", family_id="@F2@"))
    assert b"@F2@" not in edit(result, operation("delete_family", family_id="@F2@", force=True))
    with pytest.raises(ValueError):
        edit(SAMPLE.read_bytes(), operation("delete_family", family_id="@F1@", force=True))


def test_whole_tree_audit_finds_opaque_dangling_and_one_sided_relationships():
    raw = data(
        "0 @I1@ INDI\n1 _OPAQUE @MISSING@\n1 FAMC @F1@\n0 @F1@ FAM\n1 HUSB @I1@\n1 CHIL @I1@\n"
    )
    audit = audit_document(Document(raw))
    assert audit["complete_scan"]
    assert {"dangling_pointer", "self_parent", "missing_reciprocal_link", "ancestry_cycle"} <= set(
        audit["issue_counts"]
    )


SPOUSE_BRANCH = data(
    "0 @HOME@ INDI\n1 FAMC @PARENTS@\n"
    "0 @SIB@ INDI\n1 FAMC @PARENTS@\n1 FAMS @MARRIAGE@\n"
    "0 @PARENT@ INDI\n1 FAMS @PARENTS@\n"
    "0 @SPOUSE@ INDI\n1 FAMS @MARRIAGE@\n1 FAMC @INLAWS@\n1 FAMS @PRIOR@\n"
    "0 @CHILD@ INDI\n1 FAMC @MARRIAGE@\n"
    "0 @STEPCHILD@ INDI\n1 FAMC @PRIOR@\n"
    "0 @INLAW@ INDI\n1 FAMS @INLAWS@\n"
    "0 @PLACEHOLDER@ INDI\n1 NAME //\n"
    "0 @EMPTY@ FAM\n"
    "0 @PARENTS@ FAM\n1 HUSB @PARENT@\n1 CHIL @HOME@\n1 CHIL @SIB@\n"
    "0 @MARRIAGE@ FAM\n1 HUSB @SIB@\n1 WIFE @SPOUSE@\n1 CHIL @CHILD@\n"
    "0 @PRIOR@ FAM\n1 WIFE @SPOUSE@\n1 CHIL @STEPCHILD@\n"
    "0 @INLAWS@ FAM\n1 HUSB @INLAW@\n1 CHIL @SPOUSE@\n"
)


def plan(raw=SPOUSE_BRANCH, **kwargs):
    return plan_document(Document(raw), "@HOME@", "@SIB@", "@SPOUSE@", **kwargs)


def branches(result):
    return [
        candidate
        for candidate in result["candidates"]
        if candidate["kind"] == "collateral_spouse_branch"
    ]


def test_spouse_branch_retains_boundary_and_all_descendants():
    result = plan(dna_review_complete=True)
    (branch,) = branches(result)
    assert branch["record_ids"] == ["@INLAW@", "@INLAWS@"]
    assert branch["status"] == "eligible"
    after = edit(SPOUSE_BRANCH, *branch["operations"])
    index = TreeIndex(Document(after))
    assert {"@HOME@", "@SIB@", "@SPOUSE@", "@CHILD@", "@STEPCHILD@"} <= index.people
    assert "@INLAW@" not in index.people and "@INLAWS@" not in index.families
    assert not audit_document(Document(after))["summary"].get("error")


@pytest.mark.parametrize(
    "extra",
    [
        "1 NOTE Research context\n",
        "1 _UID External identity\n",
        "1 EVEN DNA match\n",
        "1 BIRT\n2 SOUR @S1@\n",
    ],
)
def test_prune_evidence_requires_manual_review_but_force_keeps_blockers(extra):
    raw = SPOUSE_BRANCH.replace(b"0 @INLAW@ INDI\n", ("0 @INLAW@ INDI\n" + extra).encode())
    if "@S1@" in extra:
        raw = raw.replace(b"0 TRLR", b"0 @S1@ SOUR\n1 TITL Source\n0 TRLR")
    (blocked,) = branches(plan(raw, dna_review_complete=True))
    assert blocked["status"] == "manual_review" and not blocked["operations"]
    (override,) = branches(plan(raw, dna_review_complete=True, force=True))
    assert override["status"] == "review_override" and override["blockers"] == blocked["blockers"]
    assert not audit_document(Document(edit(raw, *override["operations"])))["summary"].get("error")


def test_unreviewed_dna_is_not_assumed_irrelevant_and_protection_cannot_be_forced():
    (candidate,) = branches(plan())
    assert "dna_relevance_not_reviewed" in candidate["blockers"]
    assert not branches(
        plan(dna_review_complete=True, protected_individual_ids=["@INLAW@"], force=True)
    )


def test_other_family_connection_prevents_spouse_branch_pruning_even_with_force():
    raw = SPOUSE_BRANCH.replace(b"0 @INLAW@ INDI\n", b"0 @INLAW@ INDI\n1 FAMC @PARENTS@\n").replace(
        b"0 @PARENTS@ FAM\n", b"0 @PARENTS@ FAM\n1 CHIL @INLAW@\n"
    )
    with pytest.raises(ValueError, match="parent/child connection"):
        plan(raw, dna_review_complete=True, force=True)


def test_placeholder_and_family_classification_checks_all_references_and_content():
    result = plan()
    candidates = {tuple(item["record_ids"]): item for item in result["candidates"]}
    assert candidates[("@PLACEHOLDER@",)]["status"] == "eligible"
    assert candidates[("@EMPTY@",)]["status"] == "eligible"
    raw = SPOUSE_BRANCH.replace(
        b"0 @PLACEHOLDER@ INDI\n", b"0 @PLACEHOLDER@ INDI\n1 _UID Keep\n"
    ).replace(b"0 @EMPTY@ FAM\n", b"0 @EMPTY@ FAM\n1 NOTE Important\n")
    candidates = {tuple(item["record_ids"]): item for item in plan(raw)["candidates"]}
    assert candidates[("@PLACEHOLDER@",)]["status"] == "manual_review"
    assert candidates[("@EMPTY@",)]["status"] == "manual_review"


def test_name_date_matches_never_confirm_duplicates():
    raw = data(
        "0 @I1@ INDI\n1 NAME Same /Name/\n1 BIRT\n2 DATE 1900\n"
        "0 @I2@ INDI\n1 NAME Same /Name/\n1 BIRT\n2 DATE 1900\n"
    )
    assert not plan_document(Document(raw), "@I1@")["candidates"]
    raw = raw.replace(
        b"1 NAME Same /Name/\n", b"1 NAME Same /Name/\n1 _UID Same-external-identity\n"
    )
    (candidate,) = plan_document(Document(raw), "@I1@", force=True)["candidates"]
    assert candidate["kind"] == "duplicate_identity_candidate"
    assert candidate["status"] == "manual_review" and not candidate["operations"]


def test_stdio_audit_planner_merge_delete_and_revision_guard(tmp_path):
    async def exercise():
        root = Path(__file__).resolve().parents[1]
        baseline = tmp_path / "tree.ged"
        baseline.write_bytes(SPOUSE_BRANCH)
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "gedcom_server", "--gedcom-file", str(baseline)],
            cwd=str(root),
            env={
                "PHOENIX_ENABLED": "false",
                "GIS_SEARCH_ENABLED": "false",
                "SEMANTIC_SEARCH_ENABLED": "false",
                "GEDCOM_HOME_PERSON_ID": "@HOME@",
                "GEDCOM_WRITES_ENABLED": "true",
                "GEDCOM_STORE_DIR": str(tmp_path / "store"),
            },
            keep_alive=False,
        )
        async with Client(transport, timeout=20) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert {"audit_tree", "plan_tree_prune"} <= names
            result = await client.call_tool(
                "plan_tree_prune",
                {
                    "expected_revision": 0,
                    "home_person_id": "@HOME@",
                    "collateral_id": "@SIB@",
                    "spouse_id": "@SPOUSE@",
                    "dna_review_complete": True,
                },
            )
            (branch,) = branches(result.data)
            proposal = await client.call_tool(
                "prepare_tree_change",
                {
                    "expected_revision": 0,
                    "reason": "Reviewed spouse-side prune",
                    "operations": branch["operations"],
                },
            )
            assert not proposal.is_error
            applied = await client.call_tool(
                "apply_tree_change",
                {"expected_revision": 0, "proposal_id": proposal.data["proposal_id"]},
            )
            assert applied.data["revision"] == 1
            audit = await client.call_tool("audit_tree", {"expected_revision": 1, "limit": 1})
            assert audit.data["complete_scan"] and audit.data["counts"]["individuals"] == 7
            assert (
                await client.call_tool("get_individual", {"individual_id": "@INLAW@"})
            ).data is None
            with pytest.raises(Exception, match="Stale"):
                await client.call_tool(
                    "plan_tree_prune", {"expected_revision": 0, "home_person_id": "@HOME@"}
                )
            with pytest.raises(Exception, match="Stale"):
                await client.call_tool("audit_tree", {"expected_revision": 0})

    asyncio.run(asyncio.wait_for(exercise(), timeout=40))


def test_force_planner_never_offers_core_placeholder_deletion():
    result = plan(force=True)
    for candidate in result["candidates"]:
        if candidate["kind"] == "placeholder_person" and candidate["record_ids"][0] in {
            "@HOME@",
            "@SIB@",
            "@SPOUSE@",
            "@CHILD@",
            "@STEPCHILD@",
            "@PARENT@",
        }:
            assert "protected_person" in candidate["blockers"]
            assert not candidate["operations"]


def test_large_spouse_branch_uses_batch_operations_and_lossless_retention():
    raw = SPOUSE_BRANCH.replace(b"0 @INLAW@ INDI\n", b"0 @INLAW@ INDI\n1 FAMC @A0@\n")
    extra = ""
    for number in range(150):
        extra += (
            f"0 @A{number}@ FAM\n1 HUSB @R{number}@\n1 CHIL "
            + ("@INLAW@" if number == 0 else f"@R{number - 1}@")
            + "\n"
        )
        extra += f"0 @R{number}@ INDI\n1 FAMS @A{number}@\n"
        if number < 149:
            extra += f"1 FAMC @A{number + 1}@\n"
    raw = raw.replace(b"0 TRLR", extra.encode() + b"0 TRLR")
    (branch,) = branches(plan(raw, dna_review_complete=True))
    assert branch["individual_count"] == 151 and branch["family_count"] == 151
    assert len(branch["operations"]) == 3
    after = edit(raw, *branch["operations"])
    assert set(TreeIndex(Document(after)).people) == {
        "@HOME@",
        "@SIB@",
        "@PARENT@",
        "@SPOUSE@",
        "@CHILD@",
        "@STEPCHILD@",
        "@PLACEHOLDER@",
    }
    assert not audit_document(Document(after))["summary"].get("error")


def test_proposal_reports_identity_evidence_and_override_indexes(tree):
    proposal = tree.prepare(
        0,
        "Reviewed record deletion",
        [operation("delete_individual", individual_id="@I6@", force=True)],
    )
    assert proposal["review"]["force_operation_indexes"] == [0]
    assert proposal["review"]["merge_identity_evidence"] == []


def test_boundary_research_note_blocks_initial_prune_and_override_is_reviewable():
    raw = SPOUSE_BRANCH.replace(
        b"1 FAMC @INLAWS@\n", b"1 FAMC @INLAWS@\n2 NOTE Relationship research\n"
    )
    (initial,) = branches(plan(raw, dna_review_complete=True))
    assert "boundary_relationship_evidence" in initial["blockers"]
    (override,) = branches(plan(raw, dna_review_complete=True, force=True))
    assert override["operations"][0]["force"]
    after = edit(raw, *override["operations"])
    assert "-2 NOTE Relationship research" in "\n".join(LosslessEditor().diff(raw, after, None))


def test_edna_is_not_misclassified_as_a_dna_reference():
    raw = SPOUSE_BRANCH.replace(b"0 @INLAW@ INDI\n", b"0 @INLAW@ INDI\n1 NAME Edna /Example/\n")
    (branch,) = branches(plan(raw, dna_review_complete=True))
    assert branch["status"] == "eligible"


def test_same_assertion_with_different_citations_merges_without_force_and_retains_both():
    raw = data(
        "0 @I1@ INDI\n1 BIRT\n2 DATE 1900\n2 SOUR @S1@\n3 PAGE A\n3 NOTE First\n4 CONT Details\n"
        "0 @I2@ INDI\n1 BIRT\n2 DATE 1900\n2 SOUR @S2@\n3 PAGE B\n3 NOTE Second\n4 CONT Other details\n"
        "0 @S1@ SOUR\n1 TITL A\n0 @S2@ SOUR\n1 TITL B\n"
    )
    after = edit(
        raw,
        operation(
            "merge_individuals",
            source_id="@I2@",
            target_id="@I1@",
            identity_evidence="Verified same archive person identifier",
        ),
    )
    assert b"3 PAGE A\n3 NOTE First\n4 CONT Details" in after
    assert b"3 PAGE B\n3 NOTE Second\n4 CONT Other details" in after
    assert not audit_document(Document(after))["issue_counts"].get("conflicting_facts")


def test_create_family_and_partner_links_do_not_infer_sex():
    raw = data("0 @I1@ INDI\n1 SEX F\n0 @I2@ INDI\n1 SEX F\n")
    after = edit(
        raw,
        operation("add_family", family_id="@F1@"),
        operation("add_relationship", family_id="@F1@", individual_id="@I1@", role="HUSB"),
        operation("add_relationship", family_id="@F1@", individual_id="@I2@", role="WIFE"),
    )
    assert after.count(b"1 SEX F") == 2
    assert after.count(b"1 FAMS @F1@") == 2
    assert not audit_document(Document(after))["summary"].get("error")


def test_structural_preparation_failure_never_advances_revision_or_changes_indexes(tree):
    original = tree.document(0)
    with pytest.raises(ValueError):
        tree.prepare(
            0,
            "Invalid reviewed structural batch",
            [
                operation("delete_individual", individual_id="@I6@"),
                operation(
                    "merge_individuals",
                    source_id="@I3@",
                    target_id="@I1@",
                    identity_evidence="Reviewed identity",
                    force=True,
                ),
            ],
        )
    assert tree.revision == 0 and tree.document(0) == original
    assert "@I6@" in state.individuals
    assert tree.db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0


def test_deletion_diff_does_not_report_unchanged_trailer_as_removed_and_added():
    raw = SAMPLE.read_bytes()
    after = edit(raw, operation("delete_individual", individual_id="@I6@"))
    diff = "\n".join(LosslessEditor().diff(raw, after, None))
    assert "-0 @I6@ INDI" in diff
    assert "-0 TRLR" not in diff and "+0 TRLR" not in diff
