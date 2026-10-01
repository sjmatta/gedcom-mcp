# Versioned tree writes

Writes are opt-in. Read-only startup remains available; its catalog now includes
progressive discovery of the whole-tree audit. Enabling writes adds preparation, apply and maintenance entry points, plus discoverable diff/history reads and a read-only pruning planner.
`audit_tree` is available with or without writes enabled.
This release supports Linux and macOS with UTF-8 GEDCOM imports.

## Baseline and current tree

`GEDCOM_FILE` always names the original import, not the editable current tree.
The server preserves its exact bytes in `baseline/original.ged`, records its
SHA-256 hash, timestamp and person/family counts, and refuses writes if either
the configured import or archive changes. The archive is mode 400, and the
container's original data mount is read-only. These protect against application
writes; host administrators can still change files. Independent backups provide
recovery from host failure or deliberate alteration.

SQLite is authoritative for current state and history. Revision zero is the
baseline. Subsequent revisions store ordered manifests of compressed,
content-addressed GEDCOM records. Unchanged records are shared, and each new
revision records its parent, hash, time, operator label, reason and operations.
Revision/object/metadata tables reject updates and deletions. Startup reconstructs
the latest committed revision; reads never replay the edit history.

Only one server may own a store. POSIX process locking prevents multiple servers
from publishing divergent in-memory versions of the same database.

## Enable locally

Use a private directory outside source control; do not point `GEDCOM_FILE` at an export.

```sh
export GEDCOM_FILE=/path/to/original.ged
export GEDCOM_WRITES_ENABLED=true
export GEDCOM_STORE_DIR=/path/to/private-tree-store
export GEDCOM_WRITE_ACTOR=family-tree-operator
python -m gedcom_server
```

The store directory must have mode 700; a new directory is created with that
mode. The operator label is configured by the server operator, **not** a verified
per-request user identity. Access to write-enabled tools must be restricted to
trusted operators by the deployment's authentication policy.

## Review and apply

1. Read `get_tree_context` for the current revision and store status.
2. Discover the required schema with `search_tools(category="changes")`.
3. Call `prepare_change` with the returned operation and its exact payload inside
   `arguments`, including `expected_revision` and `reason`.
   `create_person` accepts given name and/or surname, optional sex (`M`, `F`, `U`)
   and note, returning a generated ID. Search existing people first; no facts or
   relationships are inferred. `update_person_name` preserves structured evidence;
   `edit_records` supports strict typed atomic batches; `restore` previews a prior
   whole-tree revision.
4. Review affected records, diff and counts. If `diff_truncated` is true, discover
   `get_tree_change_diff` and invoke it through `call_research_tool`, following
   `next_offset` until every diff page is reviewed.
5. Obtain authorization for this specific proposal, then call `apply_tree_change`.

For example:

```json
{"operation":"edit_records","arguments":{
  "expected_revision":3,"reason":"Attach research context",
  "operations":[{"op":"add_note","record_id":"@I123@","text":"Review census household"}]
}}
```

The example is the argument payload for `prepare_change`. Detailed operation
schemas are discoverable and excluded from the initial advertised catalog.
Unknown operation fields and incorrect types are rejected before preparation.

Preparation persists a proposal but does not change query results. Applying a
stale proposal fails. Repeating an already applied proposal returns its original
revision without adding another edit. Related operations in a batch commit
atomically; unsupported operations abort the entire preparation.

Supported operation dictionaries:

| `op` | Required fields | Optional fields |
| --- | --- | --- |
| `add_note` | `record_id`, `text` | — |
| `add_source` | `title` | `author`, `publication` |
| `add_event` | `record_id`, `tag`, `source_id` | `date`, `place`, `description`, `page` |
| `add_citation` | `record_id`, `path`, `source_id` | `page` |
| `replace_value` | `record_id`, `path`, `old_value`, `value` | — |

Values in this release are single-line text of at most 200 UTF-8 bytes.
Sources get stable collision-resistant IDs shown in the prepared diff; cite a
new source in a subsequent proposal after accepting it. Events require an
existing source. A citation is attached to a selected level-one event.

Paths select exact sibling occurrences, for example:

```json
{
  "op": "replace_value",
  "record_id": "@I123@",
  "path": [{"tag": "BIRT", "index": 0}, {"tag": "DATE", "index": 0}],
  "old_value": "1900",
  "value": "ABT 1900"
}
```

Corrections support NAME, SEX, and event DATE/PLAC fields. Fields with child tags
are refused to avoid contradictory values, including NAME with GIVN/SURN.
For structured name corrections use `prepare_change(operation="update_person_name", arguments=...)`, or batch
`update_name`, with the exact old NAME, complete new NAME, and explicit given-name
and surname components. It updates GIVN/SURN without removing name citations,
other subordinate fields, or alternate NAME occurrences. Read `get_record` first;
`name_index` selects the zero-based NAME occurrence. Blank components mean unknown.
Include retained prefixes/suffixes in the complete new NAME where appropriate.
Person creation uses the same reviewed proposal workflow. Structural changes use explicit operations
described below; direct value replacement never changes relationship pointers.
Notes and sources preserve research context; edits do not establish historical
truth merely because they have a citation. Preserve uncertainty in the value,
source, note and reason rather than replacing it with an unsupported assertion.

## Structural edits and reviewed overrides

All structural operations use the same `prepare_change(operation="edit_records", arguments=...)` → complete diff
review → authorized `apply_tree_change` sequence. Preparation changes no query
results. Apply retains the existing stale-revision, verified-backup, atomic commit,
read-publication, search refresh and whole-tree restore guarantees. The proposal
includes `review.force_operation_indexes` and `review.merge_identity_evidence` so
reviewers can see every override and the stated basis for identity consolidation.

| `op` | Required fields | Optional fields |
| --- | --- | --- |
| `add_individual` | `individual_id` (new `@ID@`), `name` | `sex`, `note` |
| `update_name` | `individual_id`, `old_name`, `name`, `given_name`, `surname` | `name_index` (default 0) |
| `add_family` | `family_id` (new `@ID@`) | — |
| `add_relationship` | `family_id`, `individual_id`, `role` | `pedigree`, `status` |
| `remove_relationship` | `family_id`, `individual_id`, `role` | `force` |
| `delete_individual` | `individual_id` | `force` |
| `delete_individuals` | `individual_ids` (1–50,000 unique IDs) | `force` |
| `delete_family` | `family_id` | `force` |
| `delete_families` | `family_ids` (1–50,000 unique IDs) | `force` |
| `merge_individuals` | `source_id`, `target_id`, `identity_evidence` | `force` |

Roles are `HUSB`, `WIFE`, or `CHIL`, used as GEDCOM relationship slots without
inferring sex or gender. Edits update both the family membership and the person’s
`FAMS`/`FAMC`. Replace a relationship by removing and adding it in the same batch.
Child links may specify `pedigree` (`birth`, `adopted`, `foster`, `sealing`) and
`status` (`challenged`, `disproven`, `proven`). These record claims, not biological
proof. Other families and opaque GEDCOM structures remain unchanged.

`add_individual` accepts a single-line name such as `Jane /Smith/` (or a name
without a surname delimiter). Its ID must be unused across all record types.
Place creation before `add_relationship`, `add_event`, or `add_note` operations
that reference the new ID to add a person with family links and sourced facts
atomically. Dates and places use the existing source-required `add_event` operation.
`prepare_create_person` is a convenient standalone creation proposal; it does not
connect relatives or invent birth/death information. All text limits still apply.

Merging redirects **all exact pointer values**, including nested and extension
pointers, from source to target. Distinct names, events, citations, notes and
identifiers are retained; byte-identical structures can coalesce. The target’s
existing structures remain first. Names/dates alone do not confirm identity:
`identity_evidence` must describe independently reviewed evidence (for example,
a verified external identity or source that explicitly identifies the same
person). This description is supplied by the caller, not independently verified
by the server. The source record is removed only within the accepted atomic edit.

Start with `force=false` (the default). After reviewing blockers, use `force=true`
**only on selected operations** to:

- Retain differing NAME/SEX/BIRT/DEAT evidence during a confirmed merge, rather
  than choosing one silently.
- Remove a selected person’s inbound non-family references and their subordinate
  structures. Every such removal appears in the diff, including header pointers.
- Remove evidence-bearing relationship subtrees or empty, unreferenced families
  carrying notes, identifiers or other metadata.

Force never permits new dangling references, wrong pointer types, ancestry
cycles, self-parenting, duplicate partner roles, or discarded conflicting family
qualifiers. Existing imported integrity errors can be repaired; new errors are
refused. A family cannot be deleted while it still has members or inbound
references from surviving records. Deleting people updates family membership;
it does not recursively delete relatives or discard family event records.

## Whole-tree audit and efficient pruning

`audit_tree(expected_revision?, offset=0, limit=100)` scans the **entire document**,
not just the home-person neighborhood. It checks all pointer-valued lines,
reciprocal family links, duplicate memberships, partner-role cardinality,
self-parenting and ancestry cycles, and flags conflicting vital structures,
uncited vital events and multiple parent families. It reports connected-component
counts and representatives. It is structural/evidence triage, not historical
verification, DNA analysis, duplicate identity confirmation, or a complete GEDCOM
standards validator. Follow `next_offset` with the returned revision until null;
a changed revision is refused rather than mixing findings.

`plan_tree_prune(expected_revision, home_person_id, collateral_id?, spouse_id?,
protected_individual_ids?, dna_review_complete=false, force=false, offset=0,
limit=50)` inventories all records and references and returns candidates with
`status`, `blockers`, explicit `record_ids`, and proposed `operations`. Nothing
is prepared or applied. Follow `next_offset` with unchanged parameters and
revision. Select candidates before passing their operations to preparation.

The planner distinguishes:

- Empty, unreferenced placeholders. Relationship links, vital data, citations,
  notes, media, identifiers and opaque fields block initial eligibility.
- Empty, unreferenced families. Membership, family events, citations, notes and
  metadata block initial eligibility; a family with members is not empty.
- External-identity duplicate candidates, always requiring identity review.
  Matching names/dates never produce a confirmed duplicate or automatic merge.
- Branches connected solely through a specified collateral relative’s spouse.
  The collateral relative must share recorded parentage with the home person and
  must not be their direct ancestor/descendant. Retain recorded parent/child relatives, their
  direct spouses, both boundary people, and **all descendants of either boundary
  person**, including children from earlier relationships. Remove the spouse
  from the relationship graph to identify components with no other connection
  to that retained core. Other family connections or explicitly protected people
  exclude a component even when force is requested.

Check DNA relevance independently and supply all relevant people in
`protected_individual_ids`. `dna_review_complete=false` blocks initial spouse
branch eligibility; the absence of DNA tags proves nothing. Recorded DNA
references, any research note, citation, external identifier, opaque extension,
other inbound reference, family metadata or evidence on the retained spouse’s
boundary link sends a branch to manual review.

Run the planner with `force=false` first. After review, `force=true` can return
`review_override` operations **while keeping the blockers visible**. It never
confirms duplicate identity, overrides the retained core or explicit protected
people, proves sole connectivity in a broken graph, or bypasses edit integrity
checks. This flag produces recommendations, not authorization to apply them.
Batch person/family deletion lets a branch be pruned in one proposal without an
operation per person. All deleted IDs and boundary changes remain reviewable in
the complete paginated diff, and the original baseline/history stay recoverable.

`prepare_tree_restore` previews returning the **whole tree** to an older revision.
Applying it creates a new revision and preserves all intervening history. It is
not a selective reversal of one older edit.

## Read consistency and search

The query parser builds candidate indexes away from active readers. Publication
occurs under the tree lock after the SQLite transaction commits. Tools and
resources hold the same lock for a complete read, preventing mixed-revision
results. Ordinary reads continue during candidate parsing, although commit,
backup validation and publication briefly block readers. This first version
rebuilds all basic indexes on a write; it does not promise incremental write speed.

Semantic results are invalidated immediately. A single background worker
captures current text, encodes outside the lock, and publishes only if its revision
still matches. Newer writes discard obsolete work. During rebuilding, semantic
search reports unavailable rather than serving old snippets. Basic queries remain
available. Derived caches are stored separately from the immutable GEDCOM.

## Backup, retention and capacity

A verified consistent local backup is required before committing an edit.
A second backup captures the accepted revision immediately afterward. If that
second backup fails, the response explicitly reports the committed revision and
`current_backup_error`; retrying does not duplicate the edit. An automatic daily
backup runs while the server remains running. Offline/server downtime is covered
by the external scheduled backup job described below.

Retention keeps the latest three local backups, up to 30 daily samples, and up to
12 monthly samples (at most 45 files, usually fewer). History itself is retained.
Automatic current-tree GEDCOM files are pruned; user-requested exports go into
`downloads/` and remain until the operator removes them.

The service refuses new edits when the database reaches `GEDCOM_MAX_STORE_BYTES`
(default 1 GiB) or free space falls below `GEDCOM_MIN_FREE_BYTES` (default 512 MiB)
plus twice the database size, reserving space for backup/journal work. These are
write guards, not a total-store quota. Backups, caches and requested exports also
consume space. `get_tree_context` reports database, total-store and free-disk bytes.
No design can guarantee free space if unrelated programs fill the same volume.

Backup files contain baseline, current state and revision history. Use the online
SQLite backup API; a filesystem copy of a live `tree.sqlite` is not a supported
recovery artifact. Automatic verification checks SQLite integrity, all compressed
record hashes, the revision chain, and baseline/current hashes. Offline deep
verification also validates and hashes every historical tree.

```sh
python -m gedcom_server.recovery verify /path/to/backup.sqlite
python -m gedcom_server.recovery restore /path/to/backup.sqlite /path/to/NEW-store
# Restart the server using GEDCOM_FILE=NEW-store/baseline/original.ged
# and GEDCOM_STORE_DIR=NEW-store, after stopping the previous server.
```

Recovery refuses an existing destination and never replaces a running store.

## Replace the editor with a library

`editing.py` defines `GedcomEditor` and the sole default-backend factory. The
contract uses bytes, stable operation dictionaries and `EditResult`; parser nodes
never cross the boundary. `document.py` contains the current implementation and
all GEDCOM syntax manipulation, including record splitting and review diffs.

`revision_storage.py` handles snapshots and private files; `writes.py` coordinates
revisions; `tree_projection.py` builds read indexes using the existing ged4py
reader; `write_tools.py` exposes MCP operations. Storage does not inspect line
levels or manipulate GEDCOM tags. `TreeStore(editor=...)` supports an injected
adapter. A replacement should pass `tests/test_editing_contract.py` and the full
write/recovery suite before changing `default_editor()`. The SQLite schema and
MCP operation contracts need not change when replacing the editing backend.

## Verification recorded 2026-09-30

The implementation passed 574 tests, Ruff/format checks, mypy, dependency checks,
ShellCheck, and resolved Compose validation. Tests cover both the default read-only
MCP catalog and the enabled write/review/read/resource/restore flow. Backup-script
tests verify successful S3/NAS read-backs and retention, and refusal to clean up
staging files when either read-back fails. External flags were also checked against
Rivendell's installed Restic CLI; live replication awaits deployment and activation.

An isolated full-tree run used 20,132 people and 6,273 families. The local and
currently deployed original GEDCOM hashes matched. Five small note edits grew the
revision database from 11.7 to 12.0 MiB (376 KiB total); the entire store, including
baseline, current export and retained local backups, occupied 87.4 MiB. Direct
in-process person lookup averaged roughly 0.7 microseconds before and after edits;
this excludes MCP/network overhead. Preview took 7.3–7.4 seconds and apply took
5.5–5.8 seconds because basic indexes are rebuilt and snapshots verified. Full
backup recovery and re-parsing took about 10 seconds and reproduced baseline and
current GEDCOM bytes exactly. Peak process memory was about 937 MiB, including the
separate recovered tree. GIS/semantic model loading was disabled for this run;
production memory and model-rebuild latency require a pilot check before activation.
