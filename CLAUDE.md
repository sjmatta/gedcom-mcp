# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GEDCOM MCP Server - A Python FastMCP3 server that enables AI assistants to query genealogy data from GEDCOM files. Provides 13 MCP tools and 4 resources for searching individuals, families, places, events, and generating narrative biographies.

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

- **models.py**: Data classes (Individual, Family, Event, Source, Place) with `to_dict()` and `to_summary()` methods
- **state.py**: Global mutable state - dictionaries for individuals, families, sources, and indexes (surname_index, birth_year_index, place_index)
- **parsing.py**: GEDCOM file parsing, called once at startup to populate state
- **core.py**: Query functions for search, relationships, ancestors/descendants
- **events.py, places.py, sources.py**: Domain-specific query functions
- **narrative.py**: Biography generation for LLM narratives
- **mcp_tools.py, mcp_resources.py**: MCP tool/resource registrations (separate from implementation)
- **helpers.py**: Utility functions (ID normalization, place parsing)
- **constants.py**: Place abbreviations, historical name mappings

### Data Flow

GEDCOM file → `parsing.load_gedcom()` at import → populates `state` module → builds indexes → MCP tools query indexed data

### Design Patterns

- Private functions use `_` prefix; public functions registered in mcp_tools.py/mcp_resources.py
- O(1) lookups via surname_index, birth_year_index, place_index
- Fuzzy matching for place/name searches using rapidfuzz
- Lazy loading for geonamescache

## Code Quality

- **Linting**: ruff with line-length 100, rules E/F/I/N/W/UP/B/C4/SIM
- **Type checking**: mypy with check_untyped_defs=true
- **Pre-commit hooks**: ruff lint/format and mypy on pre-commit; pytest on pre-push

## Testing

Tests are in `tests/` with fixtures in `conftest.py`. Test files mirror module structure:
- test_gedcom_server.py (core data loading and queries)
- test_events.py, test_places.py, test_sources.py, test_narrative.py
- test_edge_cases.py, test_relationships.py, test_helpers.py

Fixtures provide sample IDs and handle data-dependent tests with `pytest.skip()` fallback.
