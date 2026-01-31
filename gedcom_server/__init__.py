"""GEDCOM Genealogy Server - FastMCP3 server for querying genealogy data.

This package provides a complete MCP server for querying genealogy data from GEDCOM files.
Optimized for large files (20K+ individuals).

Usage:
    gedcom-server --gedcom-file /path/to/tree.ged
    GEDCOM_FILE=/path/to/tree.ged python -m gedcom_server
"""

from fastmcp import FastMCP

from .mcp_resources import register_resources
from .mcp_tools import register_tools
from .parsing import load_gedcom
from .state import configure
from .telemetry import initialize_tracing

# Initialize tracing FIRST (before creating server)
# This is a no-op if PHOENIX_ENABLED is not set to 'true'
initialize_tracing()

# Initialize FastMCP server
mcp = FastMCP("GEDCOM Genealogy Server")

# Register tools and resources
register_tools(mcp)
register_resources(mcp)

_initialized = False


def initialize():
    """Initialize the server: configure from env vars and load GEDCOM data.

    Called automatically on first use or can be called explicitly.
    Safe to call multiple times.
    """
    global _initialized
    if _initialized:
        return
    configure()
    load_gedcom()
    _initialized = True


__all__ = ["mcp", "initialize"]
