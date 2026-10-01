"""MCP interface for versioned changes; delegates to the revision coordinator."""

import os
import uuid

from . import state
from .revision_storage import digest, immutable_file
from .writes import require_store


def register_write_tools(mcp):
    """Only expose mutation tools when explicitly enabled at process startup."""
    if os.getenv("GEDCOM_WRITES_ENABLED", "false").lower() != "true":
        return

    @mcp.tool(annotations={"readOnlyHint": True})
    @state.synchronized
    def get_tree_revision() -> dict:
        """Get current revision, immutable baseline checksum, and backup/search status."""
        return require_store().status()

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def prepare_create_person(
        expected_revision: int,
        reason: str,
        given_name: str = "",
        surname: str = "",
        sex: str | None = None,
        note: str | None = None,
    ) -> dict:
        """Prepare adding a new person to the family tree; does not apply the edit.

        Provide given_name and/or surname, preserving uncertainty. Search existing
        people first to avoid duplicates. A unique individual_id is returned with
        the proposal and complete diff. Review it and obtain user authorization
        before calling apply_tree_change. Sex is optional M/F/U; never inferred.
        No dates or relationships are inferred. Add sourced events and explicit
        family links afterward, or use add_individual in prepare_tree_change to
        create and link a person atomically in a single reviewed batch.
        """
        from .document import Document

        given_name = Document.value(given_name, required=False).strip()
        surname = Document.value(surname, required=False).strip()
        if not (given_name or surname) or "/" in given_name or "/" in surname:
            raise ValueError("Provide given_name and/or surname without GEDCOM slash delimiters")
        individual_id = f"@I{uuid.uuid4().hex}@"
        operation = {
            "op": "add_individual",
            "individual_id": individual_id,
            "name": f"{given_name} /{surname}/".strip() if surname else given_name,
        }
        if sex is not None:
            operation["sex"] = sex
        if note is not None:
            operation["note"] = note
        proposal = require_store().prepare(expected_revision, reason, [operation])
        return {**proposal, "individual_id": individual_id}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def prepare_update_person_name(
        expected_revision: int,
        reason: str,
        individual_id: str,
        old_name: str,
        name: str,
        given_name: str,
        surname: str,
        name_index: int = 0,
    ) -> dict:
        """Prepare a person's name correction, preserving name evidence and alternate names.

        Read get_record first. old_name must match the exact selected NAME value;
        name_index is its zero-based occurrence (default primary NAME). Supply the
        complete new GEDCOM name (e.g. Jane /Smith/) and explicit given_name/surname
        components, including empty strings when unknown. Existing GIVN/SURN fields
        are synchronized; citations, nicknames, prefixes/suffixes, TYPE and unknown
        fields are retained. Include any retained prefixes/suffixes in the complete
        name as appropriate. Other NAME occurrences are untouched. No identity
        merge is inferred. Review the diff and obtain user authorization before
        apply_tree_change. Batch edits use the update_name operation with these fields.
        """
        return require_store().prepare(
            expected_revision,
            reason,
            [
                {
                    "op": "update_name",
                    "individual_id": individual_id,
                    "old_name": old_name,
                    "name": name,
                    "given_name": given_name,
                    "surname": surname,
                    "name_index": name_index,
                }
            ],
        )

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def prepare_tree_change(expected_revision: int, reason: str, operations: list[dict]) -> dict:
        """Prepare and validate a change; returns a diff without changing the tree.

        Operations: add_note(record_id,text); add_source(title,author?,publication?);
        add_event(record_id,tag,source_id,date?,place?,description?,page?);
        add_citation(record_id,path,source_id,page?);
        replace_value(record_id,path,old_value,value).
        Structural operations: add_individual(individual_id,name,sex?,note?);
        update_name(individual_id,old_name,name,given_name,surname,name_index?);
        add_family(family_id);
        add_relationship(family_id,individual_id,role,pedigree?,status?);
        remove_relationship(family_id,individual_id,role,force?);
        delete_individual(individual_id,force?); delete_individuals(individual_ids,force?);
        delete_family(family_id,force?); delete_families(family_ids,force?);
        merge_individuals(source_id,target_id,identity_evidence,force?).
        Roles are HUSB/WIFE/CHIL, never inferred from sex. Both sides are updated.
        add_individual requires a new @ID@ and name (GEDCOM /surname/ optional).
        Create first, then add relationships/events using its ID in the same batch.
        Deletion uses explicit IDs, never an implicit descendant walk. Families
        must have no members or inbound references. Merges redirect all pointers,
        preserve distinct evidence, and require identity evidence beyond names/dates.
        force defaults false: do not use initially. After reviewing blockers, it
        permits evidence-bearing family deletion, explicit removal of inbound
        person references, or retaining conflicting merge facts. It never waives
        integrity, revision, backup, diff-review or user-authorization requirements.
        Each operation includes op. Paths are lists of {tag,index}, with zero-based
        sibling occurrence indexes. Review the diff before calling apply_tree_change.
        Use update_name or prepare_update_person_name for names with subordinate tags.
        Sources created here receive an ID visible in the diff; cite them in a later proposal.
        """
        return require_store().prepare(expected_revision, reason, operations)

    @mcp.tool(annotations={"readOnlyHint": True})
    def plan_tree_prune(
        expected_revision: int,
        home_person_id: str,
        collateral_id: str | None = None,
        spouse_id: str | None = None,
        protected_individual_ids: list[str] | None = None,
        dna_review_complete: bool = False,
        force: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Inspect the whole tree and propose conservative pruning candidates, without edits.

        Finds empty placeholders, empty families and external-identity duplicate
        candidates (never confirms identity from names/dates). For a collateral/spouse
        pair, retain recorded parent/child relatives, their direct spouses, and all descendants of
        both boundary people. Only branches connected solely through that spouse
        can qualify. Check DNA independently and list DNA-relevant protected IDs;
        absent DNA tags are not proof of irrelevance. Notes, citations, identifiers,
        opaque extensions and other references trigger manual review.
        Start with force=false. After reviewing blockers, force=true returns explicit
        override operations while preserving blockers. It never overrides protected
        core people, sole-connectivity checks or graph integrity. Follow next_offset
        with unchanged parameters and revision. Pass selected operations to
        prepare_tree_change, review its full diff, and obtain authorization to apply.
        """
        from .pruning import plan_tree_prune as run_plan

        return run_plan(
            expected_revision,
            home_person_id,
            collateral_id,
            spouse_id,
            protected_individual_ids,
            dna_review_complete,
            force,
            offset,
            limit,
        )

    @mcp.tool(annotations={"readOnlyHint": True})
    @state.synchronized
    def get_tree_change_diff(proposal_id: str, offset: int = 0, limit: int = 500) -> dict:
        """Read a prepared diff in pages; follow next_offset until null before approval.

        Use this when prepare_tree_change or prepare_tree_restore reports diff_truncated.
        """
        return require_store().proposal_diff(proposal_id, offset, limit)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
    def apply_tree_change(proposal_id: str, expected_revision: int) -> dict:
        """Apply a reviewed proposal atomically after a verified local backup.

        Requires user authorization for this specific prepared diff. Refuses stale
        revisions; retrying an applied proposal does not create another revision.
        """
        return require_store().apply(proposal_id, expected_revision)

    @mcp.tool(annotations={"readOnlyHint": True})
    @state.synchronized
    def get_tree_history(limit: int = 20) -> list[dict]:
        """List immutable revisions with reason, operator label, timestamp, and hash."""
        return require_store().history(limit)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def prepare_tree_restore(expected_revision: int, restore_revision: int, reason: str) -> dict:
        """Preview restoring an older tree as a new revision, preserving all history.

        This restores the entire tree, including reversing all later changes.
        Review the diff, then authorize apply_tree_change for the returned proposal.
        """
        return require_store().prepare(expected_revision, reason, [], restore_revision)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    @state.synchronized
    def backup_tree() -> dict:
        """Create and verify a consistent local backup containing baseline and history."""
        return require_store().backup()

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    @state.synchronized
    def export_tree_revision(revision: int) -> dict:
        """Create a lossless, read-only GEDCOM export inside the private store."""
        tree = require_store()
        data = tree.document(revision)
        path = immutable_file(
            tree.directory / "downloads" / f"revision-{revision}-{digest(data)}.ged", data
        )
        return {"revision": revision, "path": str(path), "sha256": digest(path.read_bytes())}
