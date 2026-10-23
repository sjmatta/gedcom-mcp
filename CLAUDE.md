# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GEDCOM MCP Server** — a Python FastMCP server that exposes a genealogy database (a GEDCOM file) to AI assistants over the Model Context Protocol. It parses the `.ged` once at startup, builds in-memory indexes, and layers evidence-preserving reads, hybrid semantic search, GIS search, opt-in versioned writes and a research ledger on top.

Interface **v2.0** advertises **9 tools read-only, or 13 with writes enabled**; about twenty specialized tools are discovered on demand. There are **6 MCP resources**. Requires Python 3.14 (`.python-version`; torch has no 3.15 wheels yet). Production tree: ~20K individuals, served over authenticated HTTP to ChatGPT, where an always-on OpenAI Dot uses it. See `API.md`, `WRITES.md`, `RESEARCH_TOOLS.md`, `SEMANTIC_SEARCH.md` and `deploy/README.md`; they are the detailed references and should be kept current.

## Layered Architecture

```
MCP surface        mcp_tools.py (core reads + discoverable research), write_tools.py
                   (prepare/apply/maintain + research ledger), discovery.py (search_tools,
                   call_research_tool, prepare_change), mcp_resources.py, http.py (Access JWT gate)
Domain logic       core, relationships, interface_reads, research_reads, research_gaps,
                   events, places, narrative, associates, sources, tree_audit, pruning
Retrieval          semantic.py + retrieval.py (passages, BM25 + dense RRF, cross-encoder rerank);
                   spatial.py + geocoding.py (3-tier geocoding, proximity/bbox search)
Writes             writes.py (TreeStore), revision_storage.py (SQLite, content-addressed,
                   immutable), editing/document/field_edits/structural_edits (lossless editor),
                   research_ledger.py (append-only hypotheses/evidence/verdicts), recovery.py
Indexes            state.py: individuals, families, sources, repositories, places, surname,
                   birth-year, place and individual-place indexes; TREE_LOCK; HOME_PERSON_ID
Parsing            parsing.py (ged4py) → models.py dataclasses; tree_projection.py rebuilds
                   detached indexes after a write
```

### Reads
- **Core tools** (always advertised): `get_tree_context`, `search_people` (name or `mode="semantic"`), `get_people` (summary/record/biography views), `get_relatives`, `get_relationship`, `get_timeline`, `get_record` (original GEDCOM subtree with `subtree_sha256`), plus `search_tools` and `call_research_tool`.
- **Discoverable research tools** run only through `call_research_tool`, which rejects anything not read-only: `get_family`, `get_source`, `search_sources`, `get_source_references`, `search_events`, `search_nearby`, `get_place_cluster`, `get_surname_origins`, `get_military_service`, `detect_pedigree_collapse`, `find_associates`, `audit_tree`, `get_research_gaps`, `list_records`; with writes enabled also `plan_tree_prune`, `get_tree_change_diff`, `get_tree_history`, `get_research_ledger`.
- Paginated reads return `snapshot` (document SHA-256) and `revision`; callers pass `expected_snapshot` and stale snapshots are refused. Results report truncation, depth limits and coverage explicitly rather than hiding incompleteness.
- `@tool` in `mcp_tools.py` passes the whole docstring as the description (FastMCP otherwise drops sections after `Args`); wrappers are thin over private `_*()` implementations and are `synchronized` on `state.TREE_LOCK`.

### Writes (opt-in, `GEDCOM_WRITES_ENABLED=true`)
- `GEDCOM_FILE` is the immutable baseline (copied to `store/baseline/original.ged`, hash-checked). SQLite in `GEDCOM_STORE_DIR` is authoritative; revisions are manifests of compressed, content-addressed records, protected by immutability triggers. One server process owns a store (POSIX lock).
- Flow: `prepare_change(operation, arguments)` persists a proposal and full diff without changing reads → the person reviews the diff → `apply_tree_change(proposal_id, expected_revision)` takes a verified backup, commits atomically, republishes indexes, refreshes semantic search in the background, and backs up again. Stale revisions are refused; retrying an applied proposal is idempotent. `maintain_tree` makes backups/exports.
- `edit_records` has 22 strict tagged operation schemas (`change_models.py`), discovered via `search_tools(category="changes")`. Every batch is checked for new integrity errors (pointers, reciprocity, cycles).
- **Research ledger** (`record_research`, `get_research_ledger`): append-only hypotheses (statement, subjects, ≥1 rival, predictions), evidence (stance plus Evidence Explained source/information/evidence types and a locator) and verdicts (status, ICD-203 likelihood, confidence, argument, disconfirmation search). Stored in the same SQLite (`research_entries`), covered by backups, never changes the tree, needs no approval. Supported/refuted verdicts require recorded evidence.
- `GEDCOM_WRITE_ACTOR` is an operator label, not a verified per-request identity.

### Semantic search (`SEMANTIC_SEARCH_ENABLED`, default off; on in production)
BGE-small v1.5 embeddings over overlapping per-person passages (identity, events, notes, family context, citations), an in-process BM25 index, reciprocal-rank fusion with per-person passage caps, and a bounded Ettin-68M cross-encoder rerank. Models are pinned and run locally on CPU. Scores are typed ranking signals, not cosine similarity; results are candidates with evidence passages, not proof. Frozen benchmarks live in `benchmarks/semantic_search/` (basic and challenge suites; compare only on identical suite hashes). Full-tree indexes must be prebuilt before deployment (see `SEMANTIC_SEARCH.md`).

### GIS (`GIS_SEARCH_ENABLED`, default on)
Three-tier geocoding (GEDCOM coordinates → geonamescache with unique matches → Nominatim at 1 req/s) in a background thread, persisted to a geocache keyed by the GEDCOM hash. `search_nearby` reports coverage so partial geocoding is visible.

### Telemetry
Optional Phoenix/Arize tracing (`PHOENIX_ENABLED`); `initialize_tracing()` must run before `FastMCP(...)` is constructed (`__init__.py` does this). Disabled in production.

## Startup and deployment

1. `__main__.py` maps CLI args (`--gedcom-file`, `--home-person`) to env vars before importing the package.
2. `__init__.py` initializes tracing, builds `FastMCP`, registers tools/resources/write tools and the discovery transform.
3. `initialize()` → `state.configure()` (dotenv without override) → `initialize_store()` (if writes enabled) → `load_gedcom()` (indexes, home person, semantic build, geocoding thread).
4. stdio via `python -m gedcom_server`, or Streamable HTTP via `python -m gedcom_server.http`, which verifies Cloudflare Access JWTs (`CF_ACCESS_CONFIG_FILE`), checks Host (`MCP_ALLOWED_HOSTS`) and rejects browser Origins.

Production (Rivendell, behind a Cloudflare MCP portal with owner-only OAuth) uses `deploy/compose.yaml` + `deploy/compose.writes.yaml`; operations, backups and rollback are in `deploy/README.md`.

## Configuration

Precedence: CLI args > environment > `.env` > defaults. Key variables: `GEDCOM_FILE` (required), `GEDCOM_HOME_PERSON_ID`, `GEDCOM_CACHE_DIR`, `SEMANTIC_SEARCH_ENABLED`, `SEMANTIC_*` (device, model cache, embedding/reranker model and revision, rerank toggle and candidates), `GIS_SEARCH_ENABLED`, `GEDCOM_WRITES_ENABLED`, `GEDCOM_STORE_DIR`, `GEDCOM_WRITE_ACTOR`, `GEDCOM_MAX_STORE_BYTES`, `GEDCOM_MIN_FREE_BYTES`, `PHOENIX_*`/`ARIZE_*`, and for HTTP `CF_ACCESS_CONFIG_FILE`, `MCP_ALLOWED_HOSTS`.

Derived caches (semantic index, geocache) sit beside the GEDCOM or in `GEDCOM_CACHE_DIR`, are keyed to the tree content, contain private tree text, and are safe to delete (they rebuild).

## Development Commands

```bash
uv sync                  # Install dependencies (Python 3.14)
uv run poe test          # pytest
uv run poe lint          # ruff
uv run poe format        # ruff format
uv run poe typecheck     # mypy
uv run poe deps          # deptry
uv run poe check         # lint + typecheck + test
uv run poe serve         # stdio server
uv run pytest tests/test_writes.py -v
```

## Code Quality

Ruff (`line-length=100`, py314, rules E,F,I,N,W,UP,B,C4,SIM), mypy (`check_untyped_defs`), deptry, pre-commit (ruff + mypy; pytest on pre-push), GitHub Actions CI on Python 3.14. Renovate keeps the Docker Python image below 3.15 until torch ships wheels.

## Testing

Tests in `tests/`, fixtures in `conftest.py` (sets env vars **before** importing `gedcom_server`), sample data in `tests/fixtures/sample.ged`, and `tests/fixtures/planted.ged` with deliberately planted evidence problems for the audit and research-gap tests. Write-path tests build a temporary `TreeStore` (see `test_writes.py`). Key files: `test_core.py`, `test_compact_interface.py`, `test_mcp_transport.py`, `test_http.py`, `test_writes.py`, `test_field_edits.py`, `test_structural_edits.py`, `test_editing_contract.py`, `test_research_reads.py`, `test_research_gaps.py`, `test_research_ledger.py`, `test_semantic.py`, `test_passage_retrieval.py`, `test_retrieval_benchmark.py`, `test_spatial.py`, `test_accuracy_regressions.py`.

## Design Patterns and Conventions

- **Evidence first**: preserve original date text, unknown tags, alternate facts, citations and qualified parent links; never infer facts or genetic parentage from names or pedigree assertions.
- **Agents propose, people approve**: tree changes only through prepare → review → apply; the ledger is the only agent write that skips approval because it never touches the tree.
- **Say what is missing**: snapshot tokens, pagination, depth/node budgets, truncation and coverage flags; a gap or missing citation means "not in this tree", not "does not exist".
- **Small advertised surface**: add new reads as discoverable research tools (read-only annotation) rather than core tools; only add a core tool when it needs a separate execution boundary.
- **ID normalization**: public functions accept `I123` or `@I123@`.
- **Single writer, many readers**: indexes are rebuilt off-lock and published under `TREE_LOCK` after commit.
