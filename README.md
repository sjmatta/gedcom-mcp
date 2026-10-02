# GEDCOM MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that enables AI assistants to query genealogy data from GEDCOM files.

## Features

Version **2.0** advertises **9 read-only tools**, or **12 with edits enabled**.
A consolidated interface covers tree context, people search, batch person views,
qualified relatives, relationships, evidence timelines and original records.
Specialized research and exact edit schemas are discovered on demand using
`search_tools`; `call_research_tool` executes reads only.

- **All research functionality retained:** source/repository reads, reverse
  citations, event search, GIS proximity, place/surname analysis, military
  evidence, associates, pedigree collapse and whole-tree audit.
- **Explicit editing stages:** `prepare_change` previews person creation, name
  corrections, atomic record batches or restoration; `apply_tree_change` applies
  a specifically reviewed proposal. `maintain_tree` creates backups/exports.
- **Evidence preserved:** original fields, unknown tags, alternate facts,
  citations, date text and qualified parent-family assertions remain available.
- **Bounded results:** summary/detail views, pagination, snapshot guards and
  traversal limits keep results useful without silently hiding incompleteness.
- **Six resources:** individual, family, source, sources, statistics and surnames.
- **Large-tree indexes:** GEDCOM parses once at startup; search and graph reads
  use in-memory indexes.

This is a new major interface, with no legacy aliases or compatibility profile.
See [API.md](API.md) for the complete interface and discovery examples,
[RESEARCH_TOOLS.md](RESEARCH_TOOLS.md) for evidence semantics and research gaps,
and [WRITES.md](WRITES.md) for versioned edit guarantees.

### Optional Features

**Semantic Search**
Enable natural language semantic matching (e.g., "coal miners in Pennsylvania", "emigrated from Ireland"):
```bash
export SEMANTIC_SEARCH_ENABLED=true
```
Requires sentence-transformers (included in dependencies). First run builds embeddings (~15-30 seconds for large files), subsequent runs load from cache.

**GIS Proximity Search**
Find people within X miles of a location or within a region's bounding box. Enabled by default with background geocoding. Results include:
- Proximity mode: Within X miles of a point
- Within mode: Inside a region's bounding box

No configuration needed - geocoding runs automatically at startup and caches results.

**Telemetry & Observability**
OpenTelemetry tracing with Arize Phoenix for debugging and performance monitoring:
```bash
export PHOENIX_ENABLED=true
```
Requires Phoenix server running (see `.env.example` and `docker-compose.yml`).

## Installation

### Using uvx (recommended, no install needed)

```bash
uvx gedcom-server --gedcom-file /path/to/your/tree.ged
```

### Using uv tool install

```bash
uv tool install gedcom-server
gedcom-server --gedcom-file /path/to/your/tree.ged
```

### From source

```bash
git clone git@github.com:sjmatta/gedcom-mcp.git
cd gedcom-mcp
uv sync
```

## Configuration

The server requires a GEDCOM file path. Optionally, you can specify a "home person" (the tree owner).

### Configuration Options

| Method | Option | Description |
|--------|--------|-------------|
| CLI arg | `--gedcom-file`, `-f` | Path to GEDCOM file |
| Env var | `GEDCOM_FILE` | Path to GEDCOM file |
| CLI arg | `--home-person`, `-p` | GEDCOM ID of home person (e.g., `@I123@`) |
| Env var | `GEDCOM_HOME_PERSON_ID` | GEDCOM ID of home person |

CLI arguments override environment variables.

If `--home-person` is not specified, the server auto-detects the most connected individual in the tree.

### Examples

```bash
# Using CLI arguments
gedcom-server --gedcom-file ~/Documents/family.ged

# Using environment variables
export GEDCOM_FILE=~/Documents/family.ged
gedcom-server

# With explicit home person
gedcom-server -f ~/Documents/family.ged -p @I500@
```

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

### Using uvx (recommended)

```json
{
  "mcpServers": {
    "gedcom": {
      "command": "uvx",
      "args": ["gedcom-server"],
      "env": {
        "GEDCOM_FILE": "/path/to/your/tree.ged"
      }
    }
  }
}
```

### Using uv tool install

```json
{
  "mcpServers": {
    "gedcom": {
      "command": "gedcom-server",
      "args": ["--gedcom-file", "/path/to/your/tree.ged"]
    }
  }
}
```

### From source

```json
{
  "mcpServers": {
    "gedcom": {
      "command": "/path/to/gedcom-mcp/.venv/bin/python",
      "args": ["-m", "gedcom_server"],
      "env": {
        "GEDCOM_FILE": "/path/to/your/tree.ged"
      }
    }
  }
}
```

## GEDCOM File

The server supports GEDCOM 5.5.1 format, which can be exported from:
- Ancestry.com
- FamilySearch
- MyHeritage
- Gramps
- Most other genealogy software

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run poe test

# Run linter
uv run poe lint

# Run formatter
uv run poe format

# Run type checker
uv run poe typecheck

# Run all checks
uv run poe check

# Start server (requires GEDCOM_FILE env var)
uv run poe serve
```

For detailed development instructions, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Pre-commit Hooks

Pre-commit hooks are configured for:
- **Pre-commit**: ruff linting, ruff formatting, mypy type checking
- **Pre-push**: pytest test suite

Install hooks:
```bash
uv run pre-commit install --install-hooks
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## ChatGPT deployment

The authenticated Rivendell deployment is documented in [deploy/README.md](deploy/README.md),
including the OAuth portal URL, service operations, credential rotation, and rollback.

## Versioned writes (opt-in)

The original GEDCOM remains an immutable baseline. Optional write tools support
reviewed field/subtree corrections, multiline notes, citations, sourced events, reciprocal
relationship edits, evidence-preserving person merges, explicit deletion/pruning,
revision history, whole-tree undo, lossless exports, and verified backups. A
record inventory locates sources, repositories, media, shared notes and custom
records for editing. Subtree hashes guard evidence-preserving updates and explicit
replacement/removal; source creation and citation can share one atomic batch. A
whole-tree audit and conservative pruning planner expose review blockers and
selected `force=true` overrides before any change is applied. Unchanged records are
shared between revisions to keep storage growth small. See [WRITES.md](WRITES.md)
for configuration, limitations, recovery, and the replaceable editor interface.
