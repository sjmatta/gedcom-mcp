# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GEDCOM MCP Server** — a Python FastMCP server that exposes a genealogy database (a parsed GEDCOM file) to AI assistants over the Model Context Protocol. It loads a `.ged` file once at startup, builds in-memory indexes, and layers structured search, fuzzy/phonetic place matching, GIS proximity/region search, vector semantic search, and a Strands Agent fallback on top of the raw genealogy graph.

The server publishes **25 MCP tools** and **6 MCP resources**. Requires Python `>=3.12`; CI matrix runs on 3.12, 3.13 and 3.14. Typical scale target: 20K+ individuals.

## Layered Architecture

The server is best understood as several layers stacked on top of the parsed GEDCOM, each adding capability while reading the same underlying state.

```
┌─────────────────────────────────────────────────────────────────┐
│ MCP surface (FastMCP)                                           │
│  - mcp_tools.py: 25 @tool registrations                         │
│  - mcp_resources.py: 6 @mcp.resource() endpoints                │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Reasoning layer                                                 │
│  - query.py: Strands Agent (Claude) with curated tool subset    │
│    (fallback for MCP clients without subagents)                 │
└─────────────────────────────────────────────────────────────────┘
┌──────────────────────┬──────────────────────┬───────────────────┐
│ Vector layer         │ GIS layer            │ Domain logic      │
│ (semantic.py)        │ (spatial.py)         │  - core.py        │
│  - sentence-         │  - 3-tier geocoding  │  - events.py      │
│    transformers      │    (gedcom →         │  - places.py      │
│  - all-MiniLM-L6-v2  │    geonamescache →   │  - narrative.py   │
│  - normalized cosine │    Nominatim)        │  - associates.py  │
│    sim, cached as    │  - haversine /       │  - sources.py     │
│    .npz next to .ged │    bbox search       │                   │
│  - opt-in env flag   │  - background thread │                   │
│  - per-individual    │  - .geocache.json    │                   │
│    embeddings        │    persisted cache   │                   │
└──────────────────────┴──────────────────────┴───────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Index layer (state.py - module-level dicts, read-only post-load)│
│  individuals, families, sources, repositories, places           │
│  surname_index, birth_year_index, place_index, individual_places│
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Parsing layer (parsing.py via ged4py)                           │
│  Walks the .ged file once, builds models.* dataclasses:         │
│  Individual, Family, Source, Repository, Citation, Event, Place │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Cross-cutting                                                   │
│  - telemetry.py: optional Phoenix/OpenTelemetry tracing         │
│  - helpers.py / constants.py: place normalization, abbreviation │
│    expansion, historical name variants                          │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 1 — Parsing (`parsing.py`)

Uses `ged4py.GedcomReader` to walk the file once and emit dataclasses defined in `models.py`:

- `Individual` — id, given/surname, sex, birth/death (date+place), `family_as_child` (FAMC), `families_as_spouse` (FAMS), `events`, `notes`
- `Family` — husband/wife/children IDs, marriage date+place
- `Event` — type (BIRT, DEAT, RESI, OCCU, IMMI, CENS, NATU, EVEN, …), date, place, description, citations, notes
- `Source` / `Repository` / `Citation` — bibliographic chain with page, text, URL
- `Place` — original, normalized, parsed components (`[city, county, state, country]`), and lat/lon (filled by the GIS layer)

Event types parsed are listed in `constants.EVENT_TAGS`. The parser does a second pass to attach source titles to citations and, after parsing, triggers semantic embedding build (if enabled) and starts the background geocoding thread.

### Layer 2 — Indexes (`state.py`)

After `parsing.load_gedcom()` runs, `state` exposes module-level dictionaries that the rest of the codebase reads from. They are populated once at startup and treated as read-only afterward (no locking, single-writer-then-many-readers model).

| Index | Maps | Used by |
| --- | --- | --- |
| `individuals` | `id → Individual` | every domain module |
| `families` | `id → Family` | every domain module |
| `sources`, `repositories` | `id → Source/Repository` | sources.py, mcp_resources |
| `surname_index` | `surname.lower() → [ids]` | surname tools |
| `birth_year_index` | `year → [ids]` | timeline/stats |
| `place_index` | `place.lower() → [ids]` | place clustering |
| `places` | `place_id → Place` | spatial layer |
| `individual_places` | `id → [place_ids]` | spatial layer (reverse lookup) |

`HOME_PERSON_ID` is set from `GEDCOM_HOME_PERSON_ID` if provided, otherwise auto-detected by `_detect_home_person()` which scores each individual on family connectivity (parents + grandparents + spouses + children).

### Layer 3 — Domain logic

| Module | Responsibility |
| --- | --- |
| `core.py` | search, lookup, navigation, ancestors/descendants, BFS traversal, relationship calculation (cousins/removeds, half-siblings, in-laws), pedigree collapse detection, statistics |
| `events.py` | timeline assembly, military service detection (event-type + keyword scan) |
| `places.py` | fuzzy + phonetic (jellyfish/Metaphone) place matching, historical name variants (`Constantinople` ↔ `Istanbul`, `Prussia` ↔ `Germany`, etc.), place clustering |
| `narrative.py` | `_get_biography` — single-call full bio with vital summary, parents/spouses/children by name (not ID), every event with full citation chain, all notes |
| `associates.py` | FAN-Club (Friends/Associates/Neighbors) discovery: time+place overlap scoring with optional relative exclusion (`_build_ancestor_set`) |
| `sources.py` | source listing/lookup |

### Layer 4 — GIS / Geospatial (`spatial.py`)

Enabled by default (`GIS_SEARCH_ENABLED`, default `true`). Two search modes:

- **proximity** — find people with events within N miles/km of a point (haversine distance)
- **within** — find people inside a region's bounding box (state, country, etc.)

**Three-tier geocoding cascade** (`_geocode_place_full`):
1. **GEDCOM-native** — coordinates already attached to the `Place` (rare, but free)
2. **`geonamescache`** — local DB of ~25K major cities, exact then fuzzy (`rapidfuzz` ratio ≥ 85)
3. **Nominatim** (OpenStreetMap) — best coverage; rate-limited to 1 req/sec via a thread-locked timestamp; provides bounding boxes used by `mode="within"` and to classify a hit as point vs. region (`_REGION_BBOX_THRESHOLD = 0.5°`)

Each cached entry records `lat/lon/source/confidence`. Confidence buckets: `high` (exact match or Nominatim importance > 0.6), `medium`, `low`.

**Persistence** — geocode results are saved next to the GEDCOM file as `<file>.geocache.json`, keyed by a SHA-256 hash of the `.ged` so the cache invalidates automatically when the tree changes. Saved every 50 places during the background run and again at completion.

**Startup behavior** — `start_geocoding_thread()` loads the cache and spawns a daemon thread that geocodes any remaining uncached places. `_geocoding_progress` (status / total / geocoded / pending / percent) is exposed in every `search_nearby` response so the LLM knows whether coverage is partial.

**Un-geocodable values** — strings like `at sea`, `unknown`, `?`, `n/a` are short-circuited so they don't waste Nominatim calls.

### Layer 5 — Vector / Semantic search (`semantic.py`)

Opt-in (`SEMANTIC_SEARCH_ENABLED=true`, default off). Uses `sentence-transformers` with the `all-MiniLM-L6-v2` model (384-dim).

**Embedding text** (`_build_embedding_text`) per individual concatenates:
- Full name and vital summary
- Parents' full names
- Each spouse with marriage date/place
- Each event with type, description, date, place, and event-level notes
- Individual-level notes (obituaries, baptismal records, biographical paragraphs)

**Indexing** — embeddings are L2-normalized at encode time, so similarity is a single dot product (`np.dot(_embeddings, query_embedding)`). Top-k via `np.argsort(...)[::-1]`, default 20, max 100. Snippet returned is the first 300 chars of the embedding text.

**Persistence** — embeddings saved as `<file>.embeddings.npz` containing `{gedcom_hash, model_name, embeddings, ids, texts}`. Cache invalidates when either the GEDCOM hash or model name changes. First build on a 20K tree takes ~15–30s; subsequent starts are near-instant.

**Lazy encoder** — query-time encoder is loaded lazily after restart so cold queries still work.

### Layer 6 — Reasoning (`query.py`)

A Strands Agent (Claude `claude-sonnet-4-20250514` by default, overridable via `GEDCOM_QUERY_MODEL` / `GEDCOM_QUERY_MAX_TOKENS`) wired up with a curated subset of the genealogy tools (no recursion into `query` itself). Exposed as the `query` MCP tool. Treated as a **fallback** for MCP clients that lack subagent capabilities — clients that can spawn subagents should use the structured tools directly.

### Layer 7 — MCP surface (`mcp_tools.py`, `mcp_resources.py`)

Tools live in `mcp_tools.py` purely as thin `@tool` wrappers around private `_*()` implementations in domain modules. `@tool` passes the whole docstring as the description: FastMCP 3+ otherwise keeps only the first paragraph of a docstring with an `Args` section, silently dropping Returns/Examples/usage notes (guarded by `test_tool_descriptions_keep_full_docstring`). Resources are URI-templated read-only views.

Tool inventory (25 total, grouped by category in source order):

| Category | Tools |
| --- | --- |
| Context (2) | `get_home_person`, `get_statistics` |
| Lookup (3) | `get_individual`, `get_biography`, `get_family` |
| Navigation (6) | `get_parents`, `get_children`, `get_spouses`, `get_siblings`, `get_ancestors`, `get_descendants` |
| Search (1) | `search_individuals` |
| Relationship (4) | `get_relationship`, `detect_pedigree_collapse`, `get_relationship_to_me`, `get_parent_families` |
| Primitives (1) | `traverse` |
| Non-agent fallback (1) | `query` |
| Semantic (1) | `semantic_search` |
| GIS (1) | `search_nearby` |
| Timeline & events (2) | `get_timeline`, `get_military_service` |
| Place analysis (1) | `get_place_cluster` |
| Surname analysis (1) | `get_surname_origins` |
| FAN Club (1) | `find_associates` |

Resources (6): `gedcom://individual/{id}`, `gedcom://family/{id}`, `gedcom://source/{id}`, `gedcom://sources`, `gedcom://stats`, `gedcom://surnames`.

### Cross-cutting — Telemetry (`telemetry.py`)

Optional Arize Cloud or local Phoenix integration via OpenTelemetry. Set both `ARIZE_SPACE_ID` and `ARIZE_API_KEY` to select Arize Cloud; otherwise tracing uses Phoenix. Each MCP tool is wrapped by `traced_tool` to record tool spans. Enable with `PHOENIX_ENABLED=true`; defaults to a local Phoenix collector at `http://localhost:6006` (override with `PHOENIX_COLLECTOR_ENDPOINT`, or legacy `PHOENIX_ENDPOINT`) and `PHOENIX_PROJECT_NAME=gedcom-server`. A `StrandsToOpenInferenceProcessor` rewrites Strands span names into OpenInference kinds (`LLM` / `TOOL` / `AGENT` / `CHAIN`) so traces render correctly in Phoenix. **Tracing must be initialized before the FastMCP server is constructed** — `__init__.py` calls `initialize_tracing()` at module top, before `FastMCP(...)`.

## Startup Flow

1. `gedcom_server/__main__.py` parses CLI args (`--gedcom-file`, `--home-person`) and pushes them into env vars before importing the package — this lets `state.configure()` see them.
2. `gedcom_server/__init__.py` runs at import time: initializes tracing, constructs `FastMCP("GEDCOM Genealogy Server")`, registers tools and resources.
3. `initialize()` (idempotent) calls:
   - `state.configure()` — `load_dotenv()` (does *not* override existing env), resolves `GEDCOM_FILE`
   - `parsing.load_gedcom()` — parses .ged → populates `state.*` dicts → builds indexes → resolves home person → triggers `semantic.build_embeddings()` and `spatial.start_geocoding_thread()`
4. `mcp.run()` enters the FastMCP stdio loop.

## Configuration

Precedence: **CLI args > environment variables > .env file > defaults**.

```bash
gedcom-server --gedcom-file ~/tree.ged --home-person @I123@
# or
export GEDCOM_FILE=~/tree.ged
export GEDCOM_HOME_PERSON_ID=@I123@
gedcom-server
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEDCOM_FILE` | (required) | Path to .ged file |
| `GEDCOM_HOME_PERSON_ID` | auto-detect | Tree owner |
| `ANTHROPIC_API_KEY` | — | Required for `query` tool |
| `GEDCOM_QUERY_MODEL` | `claude-sonnet-4-20250514` | Strands Agent model |
| `GEDCOM_QUERY_MAX_TOKENS` | `4096` | Strands Agent token cap |
| `SEMANTIC_SEARCH_ENABLED` | `false` | Build/use vector embeddings |
| `GIS_SEARCH_ENABLED` | `true` | Geocode + GIS search |
| `PHOENIX_ENABLED` | `false` | OpenTelemetry tracing on |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Phoenix collector; legacy `PHOENIX_ENDPOINT` also accepted |
| `ARIZE_SPACE_ID`, `ARIZE_API_KEY` | — | Select Arize Cloud when both are set |
| `PHOENIX_PROJECT_NAME` | `gedcom-server` | Project name in Phoenix UI |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | inherits `PHOENIX_ENDPOINT` | Strands SDK export target |

## Caches & On-disk Artifacts

Both written next to the GEDCOM file, both keyed by SHA-256 of the .ged for automatic invalidation:

| Path | Producer | Format | Purpose |
| --- | --- | --- | --- |
| `<tree>.ged.embeddings.npz` | `semantic.py` | NumPy compressed | Persisted vector index |
| `<tree>.geocache.json` | `spatial.py` | JSON dict | Persisted geocode results |

Deleting either is safe — they will be rebuilt on next startup.

## Development Commands

All commands use `uv` (package manager) and `poethepoet` (task runner):

```bash
uv sync                  # Install dependencies
uv run poe test          # Run pytest test suite
uv run poe lint          # Run ruff linting
uv run poe format        # Run ruff formatting
uv run poe typecheck     # Run mypy type checking
uv run poe deps          # Run deptry (unused/missing dependency check)
uv run poe check         # lint + typecheck + test
uv run poe serve         # Start FastMCP server (stdio)
```

Targeted test runs:

```bash
uv run pytest tests/test_places.py -v
uv run pytest tests/test_core.py::test_search_individuals -v
```

## Code Quality

- **Ruff** — `line-length=100`, target `py312`, rules `E,F,I,N,W,UP,B,C4,SIM`, `E501` ignored
- **Mypy** — `python_version=3.12`, `check_untyped_defs=true`, `warn_unused_ignores=true`, lenient on untyped defs and missing `import-untyped`
- **Deptry** — runs in `poe deps`, ignores `DEP002` (dev-only deps in main code)
- **Pre-commit** — ruff (`--fix` + format) and mypy on `pre-commit`; pytest on `pre-push`
- **CI** — GitHub Actions runs lint, format check, typecheck, and tests on Python 3.12 + 3.13 + 3.14

## Testing

Tests live in `tests/`, fixtures in `conftest.py`, sample data in `tests/fixtures/sample.ged`. Test files mirror module structure:

| Test file | Covers |
| --- | --- |
| `test_gedcom_server.py` | Core data loading and queries |
| `test_events.py`, `test_places.py`, `test_sources.py`, `test_narrative.py` | Domain features |
| `test_edge_cases.py`, `test_relationships.py`, `test_helpers.py` | Edge cases / utilities |
| `test_semantic.py`, `test_spatial.py` | Vector / GIS layers |
| `test_telemetry.py`, `test_configuration.py` | Cross-cutting |
| `test_query.py` | Strands Agent natural-language tool |
| `test_associates.py` | FAN Club analysis |
| `test_mcp_resources.py` | MCP resource endpoints |
| `test_new_features.py` | Integration tests for recent features |
| `test_bulk.py` | Performance tests |

**Fixture strategy:** `conftest.py` sets env vars **before** importing `gedcom_server` (critical — `state.configure()` reads them at import time). Data-dependent fixtures (`individual_with_parents`, `family_with_multiple_children`, etc.) `pytest.skip()` when sample.ged lacks the required shape.

## Design Patterns and Conventions

- **Public/private split** — every domain module defines `_*()` functions; MCP wrappers in `mcp_tools.py` are zero-logic adapters. Easy to call internals from `query.py` Strands tools without going through MCP.
- **Single-pass load, read-only thereafter** — no locks, no reload; restart the server to pick up `.ged` changes.
- **Place identity** — `get_place_id` = first 12 chars of MD5 of normalized place string (lowercase, abbreviation expansion, whitespace collapse). Both indexes and the geocache key on this.
- **ID normalization** — every public function accepts `I123` or `@I123@`; `_normalize_lookup_id` round-trips through the canonical `@I123@` form.
- **Lazy expensive resources** — geonamescache is a module-level singleton (`_get_geonames_cache`); the sentence-transformers encoder loads on first use after a cache hit.
- **Background-only blocking work** — geocoding runs in a daemon thread so startup doesn't pay the Nominatim rate limit; `search_nearby` reports geocoding progress so the model can interpret partial results.
- **Optional features fail silently** — missing `sentence-transformers` or `requests` logs a warning instead of crashing.
