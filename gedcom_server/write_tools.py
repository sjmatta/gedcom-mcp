"""MCP interface for versioned changes; delegates to the revision coordinator."""

import os

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
    def prepare_tree_change(expected_revision: int, reason: str, operations: list[dict]) -> dict:
        """Prepare and validate a change; returns a diff without changing the tree.

        Operations: add_note(record_id,text); add_source(title,author?,publication?);
        add_event(record_id,tag,source_id,date?,place?,description?,page?);
        add_citation(record_id,path,source_id,page?);
        replace_value(record_id,path,old_value,value).
        Each operation includes op. Paths are lists of {tag,index}, with zero-based
        sibling occurrence indexes. Review the diff before calling apply_tree_change.
        Names with subordinate tags and all relationship edits are refused.
        Sources created here receive an ID visible in the diff; cite them in a later proposal.
        """
        return require_store().prepare(expected_revision, reason, operations)

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
