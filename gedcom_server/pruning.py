"""Revision-bound prune planning; candidate identity never constitutes approval."""

import re
from collections import defaultdict

from .document import Document
from .tree_audit import TreeIndex, audit_document

EMPTY_NAMES = {"", "//", "/ /", "?", "unknown", "unknown /unknown/"}


def evidence_blockers(index, record):
    start = index.records[record][0]
    end = index.doc.end(start)
    blockers = set()
    for line in index.doc.lines[start + 1 : end]:
        if line.tag in {"NOTE", "SOUR", "OBJE"}:
            blockers.add("research_note_or_evidence")
        if line.tag in {"REFN", "RIN", "UID", "EXID", "AFN", "RFN"} or line.tag.startswith("_"):
            blockers.add("external_identifier_or_extension")
        if "DNA" in line.tag.upper() or re.search(r"\bDNA\b", line.value, re.IGNORECASE):
            blockers.add("recorded_dna_relevance")
    return sorted(blockers)


def walk(start, edges):
    reached = set(start)
    pending = list(reached)
    while pending:
        current = pending.pop()
        for neighbor in edges.get(current, set()) - reached:
            reached.add(neighbor)
            pending.append(neighbor)
    return reached


def plan_document(
    doc,
    home_person_id,
    collateral_id=None,
    spouse_id=None,
    protected_individual_ids=None,
    dna_review_complete=False,
    force=False,
):
    index = TreeIndex(doc)
    if home_person_id not in index.people:
        raise ValueError("A valid home_person_id is required")
    protected = set(protected_individual_ids or []) | {home_person_id}
    if not protected <= index.people:
        raise ValueError("Protected people must exist in this revision")
    candidates: list[dict] = []
    core = set(protected)
    for person in sorted(index.people):
        values = index.values(person, {"NAME"})
        if values and any(value.strip().lower() not in EMPTY_NAMES for _, value in values):
            continue
        blockers = set(evidence_blockers(index, person))
        if person in protected:
            blockers.add("protected_person")
        if index.references[person] or index.links[person]:
            blockers.add("relationship_or_inbound_reference")
        # Truly empty means no vital facts, nested notes, opaque fields or IDs.
        start = index.records[person][0]
        for line in doc.lines[start + 1 : doc.end(start)]:
            if not (
                (line.tag == "NAME" and line.value.strip().lower() in EMPTY_NAMES)
                or (line.tag == "SEX" and line.value in {"", "U"})
            ):
                blockers.add("nonempty_record_content")
        candidates.append(
            {
                "kind": "placeholder_person",
                "record_ids": [person],
                "status": "manual_review" if blockers else "eligible",
                "blockers": sorted(blockers),
                "operations": []
                if blockers
                else [{"op": "delete_individual", "individual_id": person}],
            }
        )
    for family in sorted(index.families):
        if index.members[family]:
            continue
        blockers = set(evidence_blockers(index, family))
        if index.children[family]:
            blockers.add("family_evidence_or_metadata")
        if index.references[family]:
            blockers.add("inbound_reference")
        candidates.append(
            {
                "kind": "empty_family",
                "record_ids": [family],
                "status": "manual_review" if blockers else "eligible",
                "blockers": sorted(blockers),
                "operations": [] if blockers else [{"op": "delete_family", "family_id": family}],
            }
        )
    # Exact external IDs are stronger identity evidence, but still require a human
    # decision. Name/date matching does not produce a confirmed duplicate.
    identities = defaultdict(set)
    for person in sorted(index.people):
        for block in index.blocks(person):
            line = block[0]
            if line.tag in {"REFN", "UID", "EXID", "_UID", "_FSFTID"} and line.value:
                identity = tuple((part.level, part.tag, part.value) for part in block)
                identities[identity].add(person)
    for identity, people in sorted(identities.items()):
        if len(people) > 1:
            candidates.append(
                {
                    "kind": "duplicate_identity_candidate",
                    "record_ids": sorted(people),
                    "status": "manual_review",
                    "blockers": ["identity_confirmation_required"],
                    "identity_tag": identity[0][1],
                    "operations": [],
                }
            )
    if bool(collateral_id) != bool(spouse_id):
        raise ValueError("Supply both collateral_id and spouse_id")
    if collateral_id:
        if (
            collateral_id not in index.people
            or spouse_id not in index.people
            or collateral_id == spouse_id
        ):
            raise ValueError("Provide two distinct existing people for the spouse boundary")
        parents, children = defaultdict(set), defaultdict(set)
        for members in index.members.values():
            parent_ids = {
                person for role, person in members if role != "CHIL" and person in index.people
            }
            child_ids = {
                person for role, person in members if role == "CHIL" and person in index.people
            }
            for child in child_ids:
                parents[child].update(parent_ids)
            for parent in parent_ids:
                children[parent].update(child_ids)
        ancestors = walk({home_person_id}, parents)
        direct_descendants = walk({home_person_id}, children)
        blood = walk(ancestors, children)
        if collateral_id not in blood or collateral_id in ancestors | direct_descendants:
            raise ValueError(
                "collateral_id must be a recorded collateral relative of the home person"
            )
        if spouse_id in blood:
            raise ValueError(
                "Spouse also has a another recorded parent/child connection; branch pruning is ineligible"
            )
        shared_families = {
            family
            for family, members in index.members.items()
            if collateral_id in {person for role, person in members if role != "CHIL"}
            and spouse_id in {person for role, person in members if role != "CHIL"}
        }
        if not shared_families:
            raise ValueError("The boundary people must be recorded partners in a family")
        # Retain recorded parent/child relatives, their direct spouses, explicit protected people,
        # and all descendants of both people at the requested boundary.
        core = blood | protected | walk({collateral_id, spouse_id}, children)
        for members in index.members.values():
            partners = {person for role, person in members if role != "CHIL"}
            if partners & blood:
                core.update(partners)
        graph = index.graph()
        full_component = walk({home_person_id}, graph)
        cut_graph = {
            key: neighbors - {spouse_id} for key, neighbors in graph.items() if key != spouse_id
        }
        visited = set()
        for neighbor in sorted(graph[spouse_id]):
            if neighbor in visited:
                continue
            component = walk({neighbor}, cut_graph)
            visited.update(component)
            if component & core or not component <= full_component:
                continue
            people, families = component & index.people, component & index.families
            blockers = set()
            if not dna_review_complete:
                blockers.add("dna_relevance_not_reviewed")
            for record in component:
                blockers.update(evidence_blockers(index, record))
                for pos in index.references[record]:
                    owner = index.owners[pos]
                    line = doc.lines[pos]
                    expected_boundary = (
                        owner == spouse_id
                        and line.level == 1
                        and line.tag in {"FAMC", "FAMS"}
                        and record in families
                    )
                    if owner not in component and not expected_boundary:
                        blockers.add("other_inbound_reference")
                if record in families and any(
                    doc.lines[pos].tag not in {"HUSB", "WIFE", "CHIL"} or doc.end(pos) != pos + 1
                    for pos in index.children[record]
                ):
                    blockers.add("family_evidence_or_metadata")
            operations = []
            for family in sorted(families):
                for role, person in index.members[family]:
                    if person == spouse_id:
                        operations.append(
                            {
                                "op": "remove_relationship",
                                "family_id": family,
                                "individual_id": spouse_id,
                                "role": role,
                            }
                        )
                        # Inspect qualifiers, notes and IDs on the retained spouse's cut link too.
                        for pos in index.children[spouse_id]:
                            if doc.lines[pos].value == family and any(
                                line.tag in {"NOTE", "SOUR", "REFN", "RIN", "UID", "EXID"}
                                or line.tag.startswith("_")
                                for line in doc.lines[pos + 1 : doc.end(pos)]
                            ):
                                blockers.add("boundary_relationship_evidence")
            if len(people) > 50000 or len(families) > 50000:
                blockers.add("branch_exceeds_single_proposal_limit")
            if people:
                operations.append({"op": "delete_individuals", "individual_ids": sorted(people)})
            if families:
                operations.append({"op": "delete_families", "family_ids": sorted(families)})
            if len(operations) > 50:
                blockers.add("branch_exceeds_single_proposal_limit")
            candidates.append(
                {
                    "kind": "collateral_spouse_branch",
                    "record_ids": sorted(component),
                    "individual_count": len(people),
                    "family_count": len(families),
                    "status": "manual_review" if blockers else "eligible",
                    "blockers": sorted(blockers),
                    "operations": [] if blockers else operations,
                    "retained_boundary": [collateral_id, spouse_id],
                    "_review_operations": operations,
                }
            )
    for candidate in candidates:
        if candidate["kind"] == "placeholder_person" and core.intersection(candidate["record_ids"]):
            candidate["blockers"] = sorted(set(candidate["blockers"]) | {"protected_person"})
            candidate["status"] = "manual_review"
            candidate["operations"] = []
        candidate["override_requested"] = force
        if (
            force
            and candidate["status"] == "manual_review"
            and not (
                {
                    "protected_person",
                    "branch_exceeds_single_proposal_limit",
                    "identity_confirmation_required",
                }
                & set(candidate["blockers"])
            )
        ):
            records = candidate["record_ids"]
            if candidate["kind"] == "placeholder_person":
                candidate["operations"] = [
                    {"op": "delete_individual", "individual_id": records[0], "force": True}
                ]
            elif candidate["kind"] == "empty_family" and not index.references[records[0]]:
                candidate["operations"] = [
                    {"op": "delete_family", "family_id": records[0], "force": True}
                ]
            elif candidate["kind"] == "collateral_spouse_branch":
                candidate["operations"] = candidate.pop("_review_operations")
                for operation in candidate["operations"]:
                    if operation["op"] in {
                        "delete_families",
                        "delete_family",
                        "delete_individuals",
                        "remove_relationship",
                    }:
                        operation["force"] = True
            if candidate["operations"]:
                candidate["status"] = "review_override"
        candidate.pop("_review_operations", None)
    audit = audit_document(doc)
    if audit["summary"].get("error"):
        # Plans are advice only. A broken graph cannot prove sole connectivity.
        for candidate in candidates:
            if candidate["kind"] == "collateral_spouse_branch":
                candidate["status"] = "manual_review"
                candidate["blockers"].append("tree_integrity_errors")
                candidate["operations"] = []
    return {
        "scope": "Whole-tree conservative pruning candidates; no changes applied. Eligible operations still require a prepared diff and authorization.",
        "dna_review_complete": dna_review_complete,
        "force": force,
        "audit_error_count": audit["summary"].get("error", 0),
        "total_candidates": len(candidates),
        "candidates": candidates,
    }


def plan_tree_prune(
    expected_revision,
    home_person_id,
    collateral_id=None,
    spouse_id=None,
    protected_individual_ids=None,
    dna_review_complete=False,
    force=False,
    offset=0,
    limit=50,
):
    from . import state
    from .writes import require_store

    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Use nonnegative offset and limit between 1 and 100")
    with state.TREE_LOCK:
        store = require_store()
        if store.revision != expected_revision:
            raise ValueError("Stale prune revision; restart planning")
        data = store.document(expected_revision)
    result = plan_document(
        Document(data),
        home_person_id,
        collateral_id,
        spouse_id,
        protected_individual_ids,
        dna_review_complete,
        force,
    )
    candidates = result["candidates"]
    result.update(
        revision=expected_revision,
        offset=offset,
        next_offset=offset + limit if offset + limit < len(candidates) else None,
    )
    result["candidates"] = candidates[offset : offset + limit]
    return result
