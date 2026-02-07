# GEDCOM MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that enables AI assistants to query genealogy data from GEDCOM files.

## Features

- **24 MCP Tools** for comprehensive genealogy research:

  **Core Tools:**
  - `get_home_person` - Get the tree owner's record
  - `get_statistics` - Tree stats (counts, date ranges, top surnames)
  - `get_individual` - Get basic details by ID
  - `get_biography` - Get comprehensive narrative package for one person
  - `get_family` - Get family info (spouses, children, marriage)

  **Navigation Tools:**
  - `get_parents` - Get parents of an individual
  - `get_children` - Get all children from all marriages
  - `get_spouses` - Get all spouses with marriage details
  - `get_siblings` - Get siblings (same parents)
  - `get_ancestors` - Ancestor tree up to N generations
  - `get_descendants` - Descendant tree up to N generations
  - `traverse` - Generic graph traversal for custom navigation

  **Search & Discovery:**
  - `search_individuals` - Search by name (partial match)
  - `semantic_search` - Vector-based semantic search (e.g., "farmers in Scotland")
  - `search_nearby` - GIS proximity search or bounding box search

  **Relationship Analysis:**
  - `get_relationship` - Calculate relationships between two people
  - `detect_pedigree_collapse` - Find ancestors appearing multiple times
  - `find_associates` - FAN Club technique (Friends, Associates, Neighbors)

  **Timeline & Events:**
  - `get_timeline` - Chronological life events for an individual
  - `get_military_service` - Find all veterans in the tree

  **Place & Surname Analysis:**
  - `get_place_cluster` - Get all people connected to a location
  - `get_surname_origins` - Analyze surname distribution and geographic origins

  **Natural Language:**
  - `query` - Natural language questions (fallback for non-agent MCP clients)

- **4 MCP Resources**:
  - `gedcom://individual/{id}` - Individual record by ID
  - `gedcom://family/{id}` - Family record by ID
  - `gedcom://stats` - Tree statistics
  - `gedcom://surnames` - All surnames with counts

- **Optimized for large files** - Parses GEDCOM once at startup, builds in-memory indexes for fast search

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
