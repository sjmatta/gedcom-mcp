"""Entry point for running the GEDCOM server as a module.

Usage:
    python -m gedcom_server --gedcom-file /path/to/tree.ged
    gedcom-server --gedcom-file /path/to/tree.ged
"""

import argparse
import os


def main():
    """Main entry point for the GEDCOM MCP server."""
    parser = argparse.ArgumentParser(
        description="GEDCOM MCP Server - Query genealogy data via MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gedcom-server --gedcom-file ~/tree.ged
  gedcom-server -f ~/tree.ged --home-person @I123@

Environment variables:
  GEDCOM_FILE           Path to GEDCOM file
  GEDCOM_HOME_PERSON_ID GEDCOM ID of home person (default: auto-detect)
""",
    )
    parser.add_argument(
        "--gedcom-file",
        "-f",
        metavar="PATH",
        help="Path to GEDCOM file (or set GEDCOM_FILE env var)",
    )
    parser.add_argument(
        "--home-person",
        "-p",
        metavar="ID",
        help="GEDCOM ID of home person, e.g. @I123@ (default: auto-detect)",
    )
    args = parser.parse_args()

    # CLI args override env vars
    if args.gedcom_file:
        os.environ["GEDCOM_FILE"] = args.gedcom_file
    if args.home_person:
        os.environ["GEDCOM_HOME_PERSON_ID"] = args.home_person

    # Import and initialize AFTER setting env vars
    from . import initialize, mcp

    initialize()
    mcp.run()


if __name__ == "__main__":
    main()
