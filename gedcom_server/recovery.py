"""Offline tree recovery: python -m gedcom_server.recovery --help."""

import argparse
import json
import sqlite3
from pathlib import Path

from .revision_storage import (
    immutable_file,
    private_directory,
    snapshot_database,
    unpack_document,
    verify_backup,
)


def restore_backup(backup: Path, destination: Path) -> dict:
    """Recover into a NEW directory only; never replace a running tree store."""
    result = verify_backup(backup)
    if destination.exists():
        raise ValueError("Recovery destination must not already exist")
    private_directory(destination)
    path = destination / "tree.sqlite"
    path.touch(mode=0o600)
    with (
        sqlite3.connect(f"{backup.resolve().as_uri()}?mode=ro", uri=True) as source,
        sqlite3.connect(path) as target,
    ):
        source.backup(target)
        baseline = unpack_document(
            target, target.execute("SELECT document FROM revisions WHERE id=0").fetchone()[0]
        )
    private_directory(destination / "baseline")
    immutable_file(destination / "baseline" / "original.ged", baseline)
    return {
        **result,
        "store_dir": str(destination),
        "gedcom_file": str(destination / "baseline" / "original.ged"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Deeply verify every historical revision")
    verify.add_argument("backup", type=Path)
    restore = commands.add_parser("restore", help="Restore into a new private directory")
    restore.add_argument("backup", type=Path)
    restore.add_argument("destination", type=Path)
    snapshot = commands.add_parser("snapshot", help="Publish a consistent snapshot of a live store")
    snapshot.add_argument("database", type=Path)
    snapshot.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        result = verify_backup(args.backup)
    elif args.command == "snapshot":
        result = snapshot_database(args.database, args.destination)
    else:
        result = restore_backup(args.backup, args.destination)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
