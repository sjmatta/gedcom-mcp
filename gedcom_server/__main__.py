"""Entry point for running the GEDCOM server as a module.

Usage:
    python -m gedcom_server
"""

from . import mcp

if __name__ == "__main__":
    mcp.run()
