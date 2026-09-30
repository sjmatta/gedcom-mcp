# Versioned tree writes

Writes are opt-in. The existing read-only startup and its 25-tool catalog remain
available unchanged. Enabling writes adds eight revision/review/backup tools.
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

1. Read `get_tree_revision`.
2. Call `prepare_tree_change` with that revision, a reason, and operations.
3. Review the affected records, diff, and counts. If `diff_truncated` is true,
   use `get_tree_change_diff` and follow `next_offset` to review the full diff.
4. Obtain authorization for the prepared change, then call `apply_tree_change`.

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

Values in this first release are single-line text of at most 200 UTF-8 bytes.
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
This release excludes person creation, deletion, merges, and relationship changes.
Notes and sources preserve research context; edits do not establish historical
truth merely because they have a citation. Preserve uncertainty in the value,
source, note and reason rather than replacing it with an unsupported assertion.

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
consume space. `get_tree_revision` reports database, total-store and free-disk bytes.
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
