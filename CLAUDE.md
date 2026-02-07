# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GEDCOM MCP Server - A Python FastMCP3 server that enables AI assistants to query genealogy data from GEDCOM files. Provides 24 MCP tools and 4 resources for searching individuals, families, places, events, semantic search, GIS queries, and generating narrative biographies.

## Development Commands

All commands use uv package manager with poethepoet task runner:

```bash
uv sync                  # Install dependencies
uv run poe test          # Run pytest test suite
uv run poe lint          # Run ruff linting
uv run poe format        # Run ruff formatting
uv run poe typecheck     # Run mypy type checking
uv run poe check         # Run lint, typecheck, and test together
uv run poe serve         # Start FastMCP server (stdio)
```

Run a single test file or test:
```bash
uv run pytest tests/test_places.py -v
uv run pytest tests/test_core.py::test_search_individuals -v
```

## Architecture

### Package Structure

The `gedcom_server/` package follows modular separation:

**Core Infrastructure:**
- **models.py**: Data classes (Individual, Family, Event, Source, Place, Citation, Repository) with `to_dict()` and `to_summary()` methods
- **state.py**: Global mutable state - dictionaries for individuals, families, sources, and indexes (surname_index, birth_year_index, place_index, individual_places)
- **parsing.py**: GEDCOM file parsing, called once at startup to populate state
- **helpers.py**: Utility functions (ID normalization, place parsing, geocoding)
- **constants.py**: Place abbreviations, historical name mappings

**Query & Analysis:**
- **core.py**: Query functions for search, relationships, ancestors/descendants, pedigree collapse
- **events.py**: Timeline and military service analysis
- **places.py**: Place clustering and geographic analysis
- **sources.py**: Source citation queries
- **narrative.py**: Biography generation for LLM narratives
- **query.py**: Natural language question answering with strands-agents (fallback for non-agent MCP clients)
- **associates.py**: FAN Club (Friends/Associates/Neighbors) discovery based on time+place overlap

**Advanced Features:**
- **semantic.py**: Semantic search with sentence-transformers (optional, enabled via SEMANTIC_SEARCH_ENABLED=true)
- **spatial.py**: GIS proximity search with geocoding (enabled by default, runs background geocoding at startup)
- **telemetry.py**: OpenTelemetry tracing integration with Phoenix (optional, enabled via PHOENIX_ENABLED=true)

**MCP Integration:**
- **mcp_tools.py**: MCP tool registrations (24 tools) - separate from implementation
- **mcp_resources.py**: MCP resource registrations (4 resources)
- **__init__.py**: Server initialization, registers tools/resources with FastMCP
- **__main__.py**: CLI entry point with argparse for --gedcom-file and --home-person flags

### Data Flow

1. **Startup**: `__init__.py` calls `initialize()` which:
   - Loads `state.configure()` to read GEDCOM_FILE from env/CLI args
   - Calls `parsing.load_gedcom()` to parse GEDCOM and populate state dictionaries
   - Builds indexes (surname_index, birth_year_index, place_index)
   - Auto-detects home person if not specified (highest connection score)
   - Optionally starts background geocoding thread (spatial.py)
   - Optionally builds semantic search embeddings (semantic.py)

2. **Query Time**: MCP tools call private `_*()` functions in domain modules → read from indexed `state` dictionaries

3. **Configuration**: CLI args (--gedcom-file, --home-person) override env vars (GEDCOM_FILE, GEDCOM_HOME_PERSON_ID)

### Design Patterns

- **Separation of concerns**: Private functions use `_` prefix; public MCP registration in mcp_tools.py/mcp_resources.py
- **O(1) lookups**: surname_index, birth_year_index, place_index for fast queries
- **Fuzzy matching**: rapidfuzz for place/name searches, jellyfish for phonetic matching
- **Lazy loading**: geonamescache loaded on-demand for geocoding
- **Background processing**: Geocoding runs in thread at startup (spatial.py)
- **Optional features**: Semantic search and telemetry are opt-in via environment variables
- **Immutable after load**: State dictionaries populated once at startup, then read-only

## Configuration

The server supports multiple configuration methods (CLI args override env vars):

```bash
# Via CLI arguments (recommended)
gedcom-server --gedcom-file ~/tree.ged --home-person @I123@

# Via environment variables
export GEDCOM_FILE=~/tree.ged
export GEDCOM_HOME_PERSON_ID=@I123@
gedcom-server

# Optional features (disabled by default)
export SEMANTIC_SEARCH_ENABLED=true  # Enable sentence-transformers semantic search
export PHOENIX_ENABLED=true          # Enable OpenTelemetry tracing to Phoenix
```

**Configuration precedence**: CLI args > Environment variables > .env file > Defaults

## Code Quality

- **Linting**: ruff with line-length 100, rules E/F/I/N/W/UP/B/C4/SIM
- **Type checking**: mypy with check_untyped_defs=true
- **Pre-commit hooks**: ruff lint/format and mypy on pre-commit; pytest on pre-push

## Testing

Tests are in `tests/` with fixtures in `conftest.py`. Test files mirror module structure:
- **test_gedcom_server.py**: Core data loading and queries
- **test_events.py, test_places.py, test_sources.py, test_narrative.py**: Domain-specific features
- **test_edge_cases.py, test_relationships.py, test_helpers.py**: Edge cases and utilities
- **test_semantic.py, test_spatial.py**: Optional features (semantic search, GIS)
- **test_telemetry.py, test_configuration.py**: Infrastructure
- **test_query.py**: Natural language query tool
- **test_associates.py**: FAN Club analysis
- **test_mcp_resources.py**: MCP resource endpoints
- **test_new_features.py**: Integration tests for recent features
- **test_bulk.py**: Performance tests

**Fixture Strategy:**
- `conftest.py` sets env vars BEFORE importing gedcom_server (critical for test isolation)
- Uses `tests/fixtures/sample.ged` as test data
- Provides data-dependent fixtures (individual_with_parents, family_with_multiple_children, etc.)
- Tests use `pytest.skip()` when fixture data not available in sample.ged

## Recent Features & Implementation Notes

**Semantic Search (semantic.py)**
- Optional feature enabled via SEMANTIC_SEARCH_ENABLED=true
- Uses sentence-transformers (all-MiniLM-L6-v2 model) to build embeddings at startup
- Embeddings built from: name, dates, places, event descriptions, notes
- Returns results with relevance scores and snippets

**GIS Proximity Search (spatial.py)**
- Enabled by default, no configuration needed
- Background geocoding thread runs at startup to populate coordinates
- Supports two modes: "proximity" (within X miles of point) and "within" (inside region bounding box)
- Uses geonamescache for geocoding, haversine for distance calculations
- Returns coverage stats to indicate geocoding progress

**FAN Club Analysis (associates.py)**
- Implements genealogist's FAN technique (Friends/Associates/Neighbors)
- Scores based on: time overlap (same year = high, ±5 years = moderate), lifespan overlap (bonus), multiple place matches
- Optionally filters out blood/marriage relatives (default: exclude_relatives=True)
- Useful for finding witnesses, godparents, migration companions

**Natural Language Query (query.py)**
- Fallback for MCP clients without subagent support
- Uses strands-agents with anthropic client for reasoning loop
- Has access to all MCP tools except itself (prevents recursion)
- Less powerful than proper subagents - recommend subagents when available

**Telemetry (telemetry.py)**
- Optional OpenTelemetry integration with Phoenix
- Enabled via PHOENIX_ENABLED=true
- Must be initialized FIRST before creating FastMCP server (see __init__.py)
