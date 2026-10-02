# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-01

### Added

- Complete field/subtree and auxiliary record editing with exact subtree hashes,
  evidence-preserving value/type updates, and explicit replacement/removal.
- Relationship qualifier updates that preserve attached citations, notes and
  extensions; apply pointer/type/reciprocity/cycle checks to every edit batch.
- Multiline UTF-8 notes and research text using CONT/CONC; notes/citations on any
  subtree, citation text/URLs, and atomic source creation/citation with explicit IDs.
- Discoverable inventory of all record types, including unreferenced auxiliary
  records; original-field reads expose subtree hashes and bounded logical text.

### Changed

- Replace the broad advertised tool catalog with nine core/read-discovery tools,
  or twelve with editing enabled. No legacy aliases or compatibility profile.
- Consolidate person search/views, qualified family navigation, relationships and
  evidence timelines. Add snapshot guards, explicit lineage, pagination, traversal
  budgets and terminal-ancestor/depth-boundary distinctions.
- Discover specialized research and exact preparation schemas on demand, with
  separate read-only execution, proposal preparation, apply and maintenance.
- Strict tagged schemas cover all 22 atomic record edit operations, including
  person creation and evidence-preserving structured name correction.
- Preserve original records, unknown fields, citations, qualified family links,
  source/GIS/analysis functionality, revision history and backup/restore behavior.
- Advertise MCP server version 2.0.0; document the new major interface.

## Earlier unreleased work

### Removed

- Internal genealogy agent and the `query` MCP tool. Clients use the structured
  genealogy tools directly; the server no longer depends on Strands or Anthropic.

### Added

- Frozen basic/challenge semantic-retrieval benchmarks, per-query judgments and
  measured baselines/results, plus an aggregate-only full-tree resource pilot.
- Matching passage evidence with applicable event, note, family, and source
  references in semantic-search results.

- Seven evidence research reads: original GEDCOM records/subtrees, source lookup
  and search, reverse source citations, structured event search, group timelines,
  and batch person reads. Preserve original evidence paths/text, include family
  events, and reject stale snapshot pagination.
- Research-tool usage and remaining traversal recommendations in `RESEARCH_TOOLS.md`.

- `get_relationship_to_me`: one shortest path to the configured home person,
  with names, family IDs, pedigree qualifiers, lineage selection and search limits.
- `get_parent_families`: all parent links and their imported qualifiers/status.
- Family events (including marriage and divorce) with citations in family records,
  biographies, timelines and semantic search. Shared timeline events appear once.

### Changed

- Semantic search uses complete overlapping passages, pinned BGE-small embeddings,
  BM25/dense rank fusion, and bounded local Ettin-68M reranking. Scores are now
  explicitly typed ranking signals rather than cosine similarity; remove old
  cosine thresholds. Content-version-4 caches require a prebuild before deployment
  at Rivendell's production limits. Write refreshes reuse unchanged vectors.

- Refresh runtime, development, and build dependencies.
  The lockfile retains CPU-only PyTorch packages for Linux deployments.

### Fixed

- Spatial searches include spouse-family events and deduplicate vital summaries
  while preserving repeated events on different dates. Bounded region searches
  retain all matching events for the selected individuals.
- Region searches support bounding boxes that cross the antimeridian.
- Kilometer searches retain their radius behavior but now report miles fields
  in miles, with explicit kilometer distances and a radius in the selected unit.
- Semantic caches use plain string arrays and validate dimensions, lengths,
  unique IDs, and finite embeddings before loading. Legacy pickle-based caches
  rebuild once; disabled or failed rebuilds clear the previous tree's index.

- Local geocoding requires unique city/jurisdiction matches; ambiguous provider
  responses remain unresolved. Old city-only cache entries are rechecked while
  successful full-query Nominatim entries are retained.
- Parent selection prefers a unique explicit birth family or a sole usable family;
  conflicting links remain visible as ambiguous, and disproven links are not traversed.
- Graph queries have depth/node/path budgets and cycle handling. Nested trees mark
  repeated references and truncation; excessive requests return an explicit error.

- Relationship labels consistently describe person 1 relative to person 2,
  including great-grandparents and deeper ancestry in cached and direct queries.
- Individual and family timelines use GEDCOM date ordering, including partial
  dates and ranges, while retaining the original date text.
- Individual imports retain burial, baptism, christening, military, and other
  event/attribute records, including occupation values, notes, and citations.
- Military discovery avoids broad civilian keywords and includes evidence labels
  distinguishing explicit service tags from possible references in prose.
- Semantic caches now track an indexed-content version. Existing caches rebuild
  once on startup with semantic search enabled, so newly imported events are searchable.

## [1.0.0] - 2025-02-07

First stable release! The GEDCOM MCP Server provides comprehensive genealogy research tools for querying family tree data from GEDCOM files.

### Added

**Core Infrastructure:**
- FastMCP3 server with 24 MCP tools for genealogy research
- GEDCOM 5.5.1 file parsing with in-memory indexing
- Configuration via CLI arguments or environment variables
- Auto-detection of "home person" (tree owner) based on connection scoring
- Comprehensive test suite with 471 tests
- Pre-commit hooks for code quality (ruff, mypy, pytest)

**Core Tools (5 tools):**
- `get_home_person` - Get the tree owner's record
- `get_statistics` - Tree statistics (counts, date ranges, top surnames)
- `get_individual` - Get basic individual details by ID
- `get_biography` - Get comprehensive narrative package with events, notes, sources
- `get_family` - Get family unit information

**Navigation Tools (7 tools):**
- `get_parents` - Get parents of an individual
- `get_children` - Get all children from all marriages
- `get_spouses` - Get all spouses with marriage details
- `get_siblings` - Get siblings (same parents)
- `get_ancestors` - Ancestor tree up to N generations with optional terminal filter
- `get_descendants` - Descendant tree up to N generations
- `traverse` - Generic graph traversal for custom navigation

**Search & Discovery (3 tools):**
- `search_individuals` - Search by name with partial matching
- `semantic_search` - Vector-based semantic search using sentence-transformers
- `search_nearby` - GIS proximity search (within X miles) or bounding box search (within region)

**Relationship Analysis (3 tools):**
- `get_relationship` - Calculate relationships between two individuals
- `detect_pedigree_collapse` - Find ancestors appearing multiple times in family tree
- `find_associates` - FAN Club technique to find Friends, Associates, and Neighbors

**Timeline & Events (2 tools):**
- `get_timeline` - Chronological life events for an individual
- `get_military_service` - Find all veterans across the entire tree

**Place & Surname Analysis (2 tools):**
- `get_place_cluster` - Get all people connected to a location
- `get_surname_origins` - Analyze surname distribution and geographic origins

**Natural Language (1 tool):**
- `query` - Natural language question answering (fallback for non-agent MCP clients)

**Optional Features:**
- **Semantic Search**: Vector-based semantic matching with sentence-transformers (all-MiniLM-L6-v2 model). Enable with `SEMANTIC_SEARCH_ENABLED=true`
- **GIS Search**: Proximity and bounding box search with background geocoding via Nominatim. Enabled by default.
- **Telemetry**: OpenTelemetry tracing integration with Arize Phoenix. Enable with `PHOENIX_ENABLED=true`

**MCP Resources (4 resources):**
- `gedcom://individual/{id}` - Individual record by ID
- `gedcom://family/{id}` - Family record by ID
- `gedcom://stats` - Tree statistics
- `gedcom://surnames` - All surnames with counts

**Performance & Optimization:**
- O(1) lookups via surname, birth year, and place indexes
- Lazy loading of optional dependencies (sentence-transformers, geonamescache)
- Cache persistence for embeddings and geocoding results
- Background geocoding thread to avoid blocking startup
- Rate-limited Nominatim API requests (1 req/sec)

### Changed
- First stable release

## [0.1.0] - 2025-01-15

### Added
- Initial development release
- Core genealogy tools (13 tools)
- GEDCOM parsing and indexing
- Basic search and navigation capabilities

[Unreleased]: https://github.com/sjmatta/gedcom-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/sjmatta/gedcom-mcp/releases/tag/v1.0.0
[0.1.0]: https://github.com/sjmatta/gedcom-mcp/releases/tag/v0.1.0
