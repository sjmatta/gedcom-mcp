# GEDCOM MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that enables AI assistants to query genealogy data from GEDCOM files.

## Features

- **13 MCP Tools** for querying genealogy data:
  - `get_home_person` - Get the tree owner's record
  - `search_individuals` - Search by name (partial match)
  - `get_individual` - Get full details by ID
  - `get_family` - Get family info (spouses, children, marriage)
  - `get_parents` - Get parents of an individual
  - `get_children` - Get all children
  - `get_spouses` - Get all spouses with marriage details
  - `get_siblings` - Get siblings (same parents)
  - `get_ancestors` - Ancestor tree up to N generations
  - `get_descendants` - Descendant tree up to N generations
  - `search_by_birth` - Search by birth year and/or place
  - `search_by_place` - Search by any place (birth, death)
  - `get_statistics` - Tree stats (counts, date ranges, top surnames)

- **4 MCP Resources**:
  - `gedcom://individual/{id}` - Individual record by ID
  - `gedcom://family/{id}` - Family record by ID
  - `gedcom://stats` - Tree statistics
  - `gedcom://surnames` - All surnames with counts

- **Optimized for large files** - Parses GEDCOM once at startup, builds in-memory indexes for fast search

## Installation

```bash
# Clone the repository
git clone git@github.com:sjmatta/gedcom-mcp.git
cd gedcom-mcp

# Install dependencies with uv
uv sync
```

## Usage

### Running the Server

```bash
# Run directly
uv run python gedcom_server.py

# Or use poe
uv run poe serve
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gedcom": {
      "command": "/path/to/gedcom-mcp/.venv/bin/python",
      "args": ["/path/to/gedcom-mcp/gedcom_server.py"]
    }
  }
}
```

### GEDCOM File

Place your GEDCOM file as `tree.ged` in the project directory. The server supports GEDCOM 5.5.1 format (exported from Ancestry.com, FamilySearch, etc.).

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
```

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
