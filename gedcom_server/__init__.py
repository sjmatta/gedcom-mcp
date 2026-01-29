"""GEDCOM Genealogy Server - FastMCP3 server for querying genealogy data.

This package provides a complete MCP server for querying genealogy data from GEDCOM files.
Optimized for large files (20K+ individuals).

Usage:
    python -m gedcom_server
"""

from fastmcp import FastMCP

from .mcp_resources import register_resources
from .mcp_tools import register_tools
from .parsing import load_gedcom

# Initialize FastMCP server
mcp = FastMCP("GEDCOM Genealogy Server")

# Register tools and resources
register_tools(mcp)
register_resources(mcp)

# Load GEDCOM data at import time
load_gedcom()

__all__ = ["mcp"]
