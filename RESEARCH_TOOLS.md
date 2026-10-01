# Genealogical research reads and remaining work

## Implemented first increment

Seven read tools are available with writes disabled or enabled:

| Tool | Purpose |
| --- | --- |
| `get_record(record_id, path?, expected_snapshot?, offset=0, limit=100)` | Original GEDCOM record/subtree fields and raw text, including alternate claims and unknown tags. |
| `get_source(source_id)` | Source metadata and its parsed repository; missing source returns null. |
| `search_sources(query, expected_snapshot?, offset=0, limit=100)` | Case-insensitive substring search in parsed title, author, publication and note. Empty query lists sources. |
| `get_source_references(source_id, page?, expected_snapshot?, offset=0, limit=100)` | Reverse traversal of every original SOUR pointer, across all record types. Optional PAGE text matches exactly. |
| `search_events(event_type?, place?, start_year?, end_year?, individual_ids?, include_undated=false, expected_snapshot?, offset=0, limit=100)` | Structured search of individual and family event/attribute tags recognized by this server, retaining original evidence fields. |
| `get_group_timeline(individual_ids, start_year?, end_year?, include_undated=false, expected_snapshot?, offset=0, limit=100)` | Chronological personal and spouse-family events for a selected group; shared family events appear once. |
| `get_individuals_batch(individual_ids)` | Basic person reads keyed by normalized ID; duplicates collapse and missing people map to null. |

Evidence reads currently scan the current document on each call; pagination bounds the number of results returned, not scan cost.

Paginated reads return `items`, `total`, `offset`, `next_offset`, `snapshot` (a SHA-256 of the current document), and `revision` (null without a revision store). Follow `next_offset` until null, retaining the same filters and passing `snapshot` as `expected_snapshot`. A changed snapshot raises an error; restart instead of combining versions. Limit is 1–500. Group and batch calls accept at most 500 IDs. An empty explicit group selects nothing; unknown group members raise errors.

Record fields have absolute paths within their owner, using tag plus zero-based occurrence among siblings. For example, `[{"tag":"BIRT","index":1}]` selects the second birth structure. Paths identify fields only within the returned snapshot. `get_record` pages by lines: concatenate `raw` across all pages to recover the selected original text. Evidence searches return complete original field structures for each matched event/citation, rather than silently discarding extension tags, continuation text or quality fields. The lossless reader currently requires UTF-8 GEDCOM, matching the document/editor layer; it does not convert other encodings.

Event filters use inclusive overlap at calendar-year precision. BEF/AFT and FROM/TO have open bounds; ABT/CAL/EST use their nominal year without inventing an uncertainty window. Original date text and parsed interval kind remain visible. Unknown dates and dates in non-European calendars are excluded from year-filtered searches unless `include_undated=true`; without year filters they remain included. Julian years are compared at year precision without day conversion. Place matching is textual and does not establish historical jurisdiction.

Use existing traversal tools to select a branch, then pass its IDs to `search_events` or `get_group_timeline`. Family events are included when a selected person occupies a recorded spouse role, rather than attributing a parent's marriage to a child. Separate searches can inspect a family's complete original record. No residence, household membership, migration, witness role or relationship is inferred.

Example investigation:

1. `search_sources("parish")` to identify a register.
2. `get_source_references("S123", page="Page 42")` to inspect citations to one entry/page.
3. `get_record(record_id, fact_path, expected_snapshot=snapshot)` to read the entire cited fact and its notes.
4. `get_group_timeline(["I12", "I13", "I14"], start_year=1820, end_year=1850)` to compare family evidence.

Sharing a broad source (such as a census collection) does not establish that people shared a document or household. PAGE, image URLs, transcription text and source provenance must be correlated before drawing conclusions. The citation's `fact_path` denotes its immediate parent structure; record-level citations have an empty path.

## Remaining recommendations — not implemented

### 1. Collateral relatives and mixed traversal

Add `get_collateral_relatives`, or extend `traverse` with ordered/mixed relationship steps. Support questions such as “find this ancestor's siblings, their spouses, and their children.” Provide explicit options for half-siblings, step-relatives and in-laws. Repeated sibling traversal alone does not express this workflow.

Return people plus typed edges, family IDs, recorded pedigree/status qualifiers and explanatory paths. Apply lineage selection consistently in both directions; exclude disproven links and preserve ambiguity. Bound nodes, edges and depth, report incomplete results, and avoid treating a birth qualifier as proof of genetic parentage.

Acceptance: multiple-parent families, shared parents, half-siblings, remarriage, adoption, pedigree collapse and cycles all retain correct paths without duplicate people or fabricated relationships.

### 2. Common ancestors and alternative relationship paths

Expose and improve the existing internal common-ancestor function. Generalize the current home-person shortest-path capability to arbitrary endpoints, with bounded alternative paths and explicit parent-lineage selection.

Distinguish nearest shared ancestors from their own ancestors, and preserve multiple descent routes through pedigree collapse. Label spouse-mediated paths separately from descent. Do not claim all paths were found when budgets are exhausted, or infer DNA sharing from tree links.

Acceptance: direct descent, unrelated people, repeated ancestors, multiple cousin lines, birth/adoptive alternatives and spouse-only connections have deterministic, qualified results and clear completeness metadata.

### 3. Scoped research gaps

Add `get_research_gaps` using `audit_tree` findings and bounded branch traversal. Report missing parent slots, uncited vital events, conflicting claims, ambiguous parent families and unresolved places, with evidence paths and an explainable ordering.

Distinguish a genuinely unrecorded parent from an ambiguous/disproven family link, dangling pointer or depth limit. A missing citation means documentation is absent in this GEDCOM, not that no external record exists. Keep research suggestions distinct from verified historical conclusions.

Acceptance: each finding identifies its scope, reason, record/path and next useful read; traversal limits never masquerade as brick walls. Prioritization is transparent rather than an unexplained confidence score.

### 4. Recorded associates

Add `get_recorded_associates` for explicit GEDCOM associations and event participation: witnesses, godparents, informants and other recorded roles. Keep these separate from the existing time/place-based `find_associates` candidates.

Implement the repository's GEDCOM 5.5.1 association structures and exporter extensions; use GEDCOM 7's role vocabulary only when actually supported by the imported format. Return the original role text, owning event, citation and path. Co-location, a shared source, and a name mentioned in prose do not by themselves establish an explicit association.

Acceptance: forward/reverse association queries preserve unknown roles and event context, resolve pointers safely and distinguish recorded associations from inferred candidates.

## Research basis

- [BCG Genealogical Proof Standard](https://www.bcgcertification.org/ethics-standards): citation, evidence correlation, conflict resolution and adequately supported conclusions motivate evidence-first reads.
- [Your Ancestor's FAN Club, Drew Smith, hosted by FamilySearch](https://cms-z-assets.familysearch.org/c2/50/170880cb940e230e4a88c839bf3e/your-ancestors-fan-club.pdf): collateral relatives, witnesses, neighbors and repeated interactions support cluster research and migration/identity investigations.
- [FamilySearch GEDCOM specification](https://gedcom.io/specifications/FamilySearchGEDCOMv7.html): reference for recorded associations, participant roles and qualified family links; version 7 is not a claim of this server's import support.

The tool designs and priorities above are implementation recommendations derived from those research practices, rather than requirements imposed by the sources.
