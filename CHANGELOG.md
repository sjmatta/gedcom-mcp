# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
