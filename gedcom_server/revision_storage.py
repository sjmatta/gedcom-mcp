"""Private, durable files and deduplicated SQLite snapshots.

No GEDCOM syntax knowledge or query-state mutation belongs in this module.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path

from .editing import GedcomEditor, default_editor

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS objects (id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY, parent INTEGER REFERENCES revisions(id),
 created TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
 operations TEXT NOT NULL, digest TEXT NOT NULL, document BLOB NOT NULL,
 proposal TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS proposals (
 token TEXT PRIMARY KEY, expected INTEGER NOT NULL REFERENCES revisions(id),
 reason TEXT NOT NULL, operations TEXT NOT NULL, digest TEXT NOT NULL,
 document BLOB NOT NULL, affected TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_object_update BEFORE UPDATE ON objects
 BEGIN SELECT RAISE(ABORT, 'objects are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_object_delete BEFORE DELETE ON objects
 BEGIN SELECT RAISE(ABORT, 'objects are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_revision_update BEFORE UPDATE ON revisions
 BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_revision_delete BEFORE DELETE ON revisions
 BEGIN SELECT RAISE(ABORT, 'revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_metadata_update BEFORE UPDATE ON metadata
 BEGIN SELECT RAISE(ABORT, 'baseline metadata is immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_metadata_delete BEFORE DELETE ON metadata
 BEGIN SELECT RAISE(ABORT, 'baseline metadata is immutable'); END;
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Private storage directory cannot be a symlink")
    if path.stat().st_mode & 0o077:
        raise ValueError(f"Storage directory must have mode 700: {path}")


def immutable_file(path: Path, data: bytes) -> Path:
    """Create a durable file once; existing content must match exactly."""
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("Immutable file was changed")
        return path
    # Publish only after file contents are durable; never overwrite another file.
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
        os.link(temporary, path)
        sync_directory(path.parent)
    finally:
        os.unlink(temporary)
    return path


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def pack_document(db: sqlite3.Connection, data: bytes, editor: GedcomEditor | None = None) -> bytes:
    """Deduplicate exact level-zero records; manifests preserve order and bytes."""
    chunks = (editor or default_editor()).records(data)
    if b"".join(chunks) != data:
        raise ValueError("Editing backend did not preserve the source bytes")
    ids = []
    for chunk in chunks:
        checksum = digest(chunk)
        row = db.execute("SELECT id FROM objects WHERE digest=?", (checksum,)).fetchone()
        if row is None:
            cursor = db.execute(
                "INSERT INTO objects(digest,data) VALUES (?,?)", (checksum, zlib.compress(chunk))
            )
            ids.append(cursor.lastrowid)
        else:
            ids.append(row[0])
    return zlib.compress(json.dumps(ids, separators=(",", ":")).encode())


def unpack_document(db: sqlite3.Connection, packed: bytes) -> bytes:
    ids = json.loads(zlib.decompress(packed))
    objects = dict(db.execute("SELECT id,data FROM objects"))
    try:
        return b"".join(zlib.decompress(objects[key]) for key in ids)
    except KeyError:
        raise ValueError("Revision references a missing GEDCOM record") from None


def verify_backup(path: Path, *, deep: bool = True, editor: GedcomEditor | None = None) -> dict:
    """Check objects and revision manifests; deep mode hashes every historical tree."""
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup failed SQLite integrity check")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup has broken revision references")
        meta = dict(db.execute("SELECT key,value FROM metadata"))
        if meta.get("schema") != "1":
            raise ValueError("Unknown backup schema")
        objects = {}
        for key, checksum, packed in db.execute("SELECT id,digest,data FROM objects"):
            raw = zlib.decompress(packed)
            if digest(raw) != checksum:
                raise ValueError("GEDCOM record checksum mismatch")
            objects[key] = raw
        rows = db.execute("SELECT id,parent,digest,document FROM revisions ORDER BY id").fetchall()
        if not rows:
            raise ValueError("Backup has no baseline")
        for expected, (revision, parent, checksum, packed) in enumerate(rows):
            ids = json.loads(zlib.decompress(packed))
            if not ids or any(key not in objects for key in ids):
                raise ValueError("Broken revision manifest")
            if revision != expected or parent != (expected - 1 if expected else None):
                raise ValueError("Broken revision chain")
            if deep or expected in (0, len(rows) - 1):
                data = b"".join(objects[key] for key in ids)
                if deep:
                    (editor or default_editor()).validate(data)
                if digest(data) != checksum:
                    raise ValueError("Revision checksum mismatch")
        if rows[0][2] != meta["baseline_sha256"]:
            raise ValueError("Baseline checksum mismatch")
        return {
            "revision": rows[-1][0],
            "baseline_sha256": rows[0][2],
            "revisions_verified": len(rows),
            "deep": deep,
        }


def snapshot_database(source: Path, destination: Path) -> dict:
    """Publish a verified snapshot of a live SQLite store without opening a writer.

    Only completed snapshots receive their final name, so external backup tools
    cannot accidentally ingest a partly written file. Destination is never replaced.
    """
    from contextlib import closing

    if destination.exists() or destination.is_symlink():
        raise ValueError("Snapshot destination already exists")
    private_directory(destination.parent)
    minimum = int(os.getenv("GEDCOM_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
    if shutil.disk_usage(destination.parent).free < minimum + source.stat().st_size * 2:
        raise ValueError("Insufficient free disk space for a safe replication snapshot")
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".sqlite.tmp")
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        with (
            closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as source_db,
            closing(sqlite3.connect(temporary_path)) as target_db,
        ):
            source_db.backup(target_db)
        result = verify_backup(temporary_path, deep=False)
        with open(temporary_path, "rb") as stream:
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o400)
        os.link(temporary_path, destination)
        sync_directory(destination.parent)
        return {"path": str(destination), **result}
    finally:
        temporary_path.unlink(missing_ok=True)
