# MCP interface, version 2

The server advertises **9 tools in read-only mode**, or **12 with writes enabled**.
Specialized operations remain available through progressive discovery. This is a
major release with no legacy tool aliases or compatibility profile.

## Core reads

| Tool | Purpose and principal arguments |
| --- | --- |
| `get_tree_context()` | Home-person summary, statistics, snapshot, revision, store/backup status and search capabilities. Start here for family context and before edits. |
| `search_people(query, mode="name", limit=50, expected_snapshot?)` | Partial-name matching or `mode="semantic"` evidence retrieval. Limit 1–100. Semantic results are candidates, not proof. |
| `get_people(individual_ids?, view="summary", expected_snapshot?)` | One/batch lookup; omitted IDs select home person. Summary: 500 IDs; parsed record with events: 100; biography with relatives and citations: 20. Missing IDs map to null; duplicates collapse. |
| `get_relatives(individual_id, relation, generations=1, view="list", lineage="default", expected_snapshot?, offset=0, limit=100, max_nodes=1000)` | Parents, children, spouses, siblings, ancestors or descendants. List, nested tree or terminal-ancestor view. Includes family-link evidence and all root parent-family assertions. |
| `get_relationship(individual_id, reference_id?, method="kinship", max_generations=10, lineage="default", max_steps=30, expected_snapshot?)` | Person 1 relative to reference (default home). Kinship labels/common ancestors or one shortest qualified family path. |
| `get_timeline(individual_ids, start_year?, end_year?, include_undated=false, expected_snapshot?, offset=0, limit=100)` | Evidence timeline for 1–500 people; shared spouse-family events appear once. Original dates, notes, citations and field paths retained. |
| `get_record(record_id, path?, expected_snapshot?, offset=0, limit=100)` | Complete original GEDCOM record/subtree, including alternate facts and unknown fields. Paginated by lines. |
| `search_tools(query="", category="research", offset=0, limit=3)` | Ranked tool discovery with exact input/output schemas and execution route. Empty query browses a category. Categories: research, changes, all. Limit 1–10. |
| `call_research_tool(name, arguments)` | Executes an available read-only operation through the normal authorization/validation pipeline. Rejects proposals, apply, backup/export, unknown and disabled tools, and recursive discovery calls. |

### Navigation and evidence semantics

`generations` is 0–20 for parents/ancestors and 0–10 for other relations.
`lineage="default"` uses selected, unambiguous parent families; `all` uses all
usable assertions; `birth`, `adopted`, `foster`, and `sealing` require explicit
matching qualifiers. Disproven links are excluded from traversal but retained in
the root's parent-family evidence. Pedigree assertions do not prove genetic parentage.

List navigation returns unique people with one shortest path. Tree navigation
marks repeated references rather than recursively expanding cycles. Terminal
ancestors have no further selected recorded parent links; a generation cutoff
never establishes a terminal ancestor. `depth_limited` explicitly reports links
beyond the selected depth. List/terminal results paginate with `offset` and
`limit` (1–500); tree view requires offset zero. `max_nodes` bounds traversal,
defaulting to 1,000 and allowing up to 50,000. Exceeded node/edge budgets fail
explicitly; reduce depth or deliberately increase the node budget.

Kinship and shortest-path relationship methods are distinct. Kinship uses default
parent selection and a common-ancestor generation bound (null permits up to 100).
Path supports explicit lineage, marriage connections and `max_steps` 1–100. It
returns one path, not all possible relationships.

Reuse the returned `snapshot` as `expected_snapshot` across pages and related
reads. Stale snapshots are rejected. Timelines/event search use inclusive year
interval overlap, preserving original date text; approximate years use their
recorded nominal year. Unknown/non-European-calendar dates pass year filters only
with `include_undated=true`. Without year filters, all dates are included.

## Discoverable research

| Operation | Purpose |
| --- | --- |
| `get_family` | Family unit, marriage and family events, children and spouse IDs. |
| `get_source`, `search_sources` | Source/repository metadata and source search. |
| `get_source_references` | Reverse citations across record types, exact fact/citation paths, page filtering. |
| `search_events` | Individual/family evidence filtered by GEDCOM tag, place, year and selected people. |
| `search_nearby` | Geographic proximity or bounding-box search, geocoding coverage and uncertainty. |
| `get_place_cluster` | People connected to an exact recorded place and associated events. |
| `get_surname_origins` | Recorded surname distribution and geographic patterns. |
| `get_military_service` | Explicit service records and separately labeled possible references. |
| `detect_pedigree_collapse` | Repeated ancestors and recorded paths. |
| `find_associates` | Friends/associates/neighbors candidates from shared time/place context. |
| `audit_tree` | Structural errors, evidence-review warnings and connected components. |

With writes enabled, discovery also exposes `plan_tree_prune`,
`get_tree_change_diff`, and `get_tree_history` as read-only research operations.
Preparation schemas are discoverable in the changes category.

Discover, then execute using the returned schema and route:

```json
{"name":"search_tools","arguments":{"query":"source citations"}}
```

```json
{"name":"call_research_tool","arguments":{
  "name":"get_source_references",
  "arguments":{"source_id":"@S1@","limit":20}
}}
```

Discovery pages include `total`, `next_offset`, and `tools`. Each definition has
`inputSchema`, `outputSchema`, annotations, and `execution`. Browse empty-query
pages to enumerate every operation; ranked searches may return no matches.
Discovery does not grant access: filtered tools cannot be discovered or dispatched.
All original operations use the standard FastMCP pipeline, including middleware.

## Optional change and maintenance tools

| Advertised tool | Purpose |
| --- | --- |
| `prepare_change(operation, arguments)` | Persist a proposal and return its diff, without changing the active tree. Operations: create_person, update_person_name, edit_records, restore. |
| `apply_tree_change(proposal_id, expected_revision)` | Apply the specifically authorized proposal atomically after a verified backup. Rejects stale revisions; applied-proposal retries are idempotent. |
| `maintain_tree(action, revision?)` | Verified local backup or lossless export of an explicit revision. Creates private files without changing the active tree. |

Obtain preparation schemas with `search_tools(category="changes")`. The returned
`execution.operation` selects `prepare_change`; provide the complete matching
`inputSchema` payload inside `arguments`, including revision and reason.

```json
{"name":"search_tools","arguments":{"query":"create a person","category":"changes"}}
```

```json
{"name":"prepare_change","arguments":{
  "operation":"create_person",
  "arguments":{"expected_revision":3,"reason":"Document sourced relative",
               "given_name":"Jane","surname":"Example"}
}}
```

`edit_records` has strict, tagged operation schemas for all 15 edit types,
including atomic person/family creation and linking, evidence edits, structured
names, explicit deletion and merging. Unknown fields and invalid types are
rejected. Detailed schemas are deferred until discovery; they do not enlarge the
initial catalog. Omitted sex is not inferred. Name changes retain evidence and
alternate names, with an exact old-value guard.

Review every diff page through discovered `get_tree_change_diff` before obtaining
user authorization and invoking `apply_tree_change`. The read dispatcher cannot
prepare/apply changes; the preparation dispatcher cannot apply or run maintenance.
See [versioned writes](WRITES.md) for safeguards and operation semantics.

## Resources

Six existing read-only resources remain: `gedcom://individual/{id}`,
`gedcom://family/{id}`, `gedcom://source/{id}`, `gedcom://sources`,
`gedcom://stats`, and `gedcom://surnames`. Tools retain evidence access for clients
that do not use resources.
