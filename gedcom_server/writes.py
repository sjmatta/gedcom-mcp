"""Opt-in, single-server revision store with lossless snapshots and recovery.

SQLite is authoritative. Export files and query indexes are rebuildable projections.
Backups use SQLite's online backup API, never a copy of a live database file.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import state
from .editing import GedcomEditor, default_editor
from .revision_storage import (
    SCHEMA,
    digest,
    immutable_file,
    now,
    pack_document,
    private_directory,
    sync_directory,
    unpack_document,
    verify_backup,
)
from .tree_projection import INDEXES, projection


class TreeStore:
    def __init__(
        self,
        baseline: Path,
        directory: Path,
        actor: str = "local-operator",
        *,
        editor: GedcomEditor | None = None,
    ):
        try:
            import fcntl
        except ImportError:
            raise ValueError(
                "Write stores currently require POSIX file locking (Linux/macOS)"
            ) from None
        if directory.is_symlink():
            raise ValueError("Tree store directory cannot be a symlink")
        self.directory = directory.resolve()
        private_directory(self.directory)
        self.editor = editor or default_editor()
        self.stop_event = threading.Event()
        self.actor = actor
        self.original = baseline.resolve()
        self.lock_file = open(self.directory / "writer.lock", "a+b")  # noqa: SIM115 - lifetime lock
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise ValueError("Another server owns this tree store") from None
        self._db: sqlite3.Connection | None = None
        try:
            for name in ("baseline", "exports", "backups", "cache", "downloads"):
                private_directory(self.directory / name)
            data = self.original.read_bytes()
            self.editor.validate(data)
            self.baseline_hash = digest(data)
            self.baseline_path = self.directory / "baseline" / "original.ged"
            immutable_file(self.baseline_path, data)
            db_path = self.directory / "tree.sqlite"
            if db_path.is_symlink():
                raise ValueError("Database cannot be a symlink")
            if not db_path.exists():
                db_path.touch(mode=0o600)
            self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(SCHEMA)
            with self.db:
                if not self.db.execute("SELECT 1 FROM revisions").fetchone():
                    initial = projection(data, self.directory)
                    self.db.executemany(
                        "INSERT INTO metadata VALUES (?,?)",
                        [
                            ("schema", "1"),
                            ("baseline_sha256", self.baseline_hash),
                            ("imported", now()),
                            ("baseline_individuals", str(len(initial.individuals))),
                            ("baseline_families", str(len(initial.families))),
                        ],
                    )
                    self.db.execute(
                        "INSERT INTO revisions VALUES (0,NULL,?,?,?,?,?,?,NULL)",
                        (
                            now(),
                            actor,
                            "Original GEDCOM import",
                            "[]",
                            self.baseline_hash,
                            pack_document(self.db, data, self.editor),
                        ),
                    )
            verify_backup(db_path, deep=False, editor=self.editor)
            if (
                self.db.execute(
                    "SELECT value FROM metadata WHERE key='baseline_sha256'"
                ).fetchone()[0]
                != self.baseline_hash
            ):
                raise ValueError("Configured GEDCOM differs from immutable baseline")
            self.revision = self.latest()["id"]
            self.export(self.revision)
            if not any((self.directory / "backups").glob("*.sqlite")):
                self.backup()
        except BaseException:
            self.close()
            raise

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise ValueError("Tree store is closed")
        return self._db

    def close(self):
        self.stop_event.set()
        if self._db is not None:
            self._db.close()
            self._db = None
        if not self.lock_file.closed:
            self.lock_file.close()

    def latest(self):
        return self.db.execute("SELECT * FROM revisions ORDER BY id DESC LIMIT 1").fetchone()

    def check_baseline(self):
        for path in (self.original, self.baseline_path):
            if digest(path.read_bytes()) != self.baseline_hash:
                raise ValueError("Immutable baseline checksum mismatch; writes refused")

    def document(self, revision: int) -> bytes:
        row = self.db.execute(
            "SELECT digest,document FROM revisions WHERE id=?", (revision,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown revision")
        data = unpack_document(self.db, row["document"])
        if digest(data) != row["digest"]:
            raise ValueError("Revision checksum mismatch")
        return data

    def export(self, revision: int) -> Path:
        data = self.document(revision)
        return immutable_file(
            self.directory / "exports" / f"revision-{revision}-{digest(data)}.ged", data
        )

    def backup(self) -> dict:
        self.check_baseline()
        path = (
            self.directory / "backups" / f"revision-{self.latest()['id']}-{uuid.uuid4().hex}.sqlite"
        )
        path.touch(mode=0o600)
        try:
            with sqlite3.connect(path) as destination:
                self.db.backup(destination)
            result = verify_backup(path, deep=False, editor=self.editor)
            with open(path, "rb") as stream:
                os.fsync(stream.fileno())
            sync_directory(path.parent)
            return {"path": str(path), **result}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def prune_backups(self, keep: int = 3):
        """Keep recent pre-write backups plus 30 daily and 12 monthly samples."""
        paths = sorted(
            (self.directory / "backups").glob("*.sqlite"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        retained = set(paths[:keep])
        days: set[str] = set()
        months: set[str] = set()
        for path in paths:
            stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            day = stamp.strftime("%Y-%m-%d")
            month = stamp.strftime("%Y-%m")
            if day not in days and len(days) < 30:
                days.add(day)
                retained.add(path)
            if month not in months and len(months) < 12:
                months.add(month)
                retained.add(path)
        for path in paths:
            if path not in retained:
                path.unlink()

    def prune_exports(self, current: Path):
        # Exports are reproducible from history. Explicit user exports live elsewhere.
        for path in (self.directory / "exports").glob("revision-*.ged"):
            if path != current:
                path.unlink()

    def check_capacity(self):
        """Refuse new changes before backup/journal work can exhaust the volume."""
        size = (self.directory / "tree.sqlite").stat().st_size
        minimum = int(os.getenv("GEDCOM_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
        maximum = int(os.getenv("GEDCOM_MAX_STORE_BYTES", str(1024 * 1024 * 1024)))
        if size >= maximum:
            raise ValueError("Revision store reached its configured size limit")
        if shutil.disk_usage(self.directory).free < minimum + size * 2:
            raise ValueError("Insufficient free disk space for a safe write and backup")

    def start_daily_backups(self):
        """One daemon per store; retention runs only after a verified backup."""

        def worker():
            import logging

            while not self.stop_event.wait(24 * 60 * 60):
                try:
                    with state.TREE_LOCK:
                        if self.stop_event.is_set():
                            return
                        self.check_capacity()
                        self.backup()
                        self.prune_backups()
                except Exception:
                    logging.getLogger(__name__).exception("Scheduled tree backup failed")

        threading.Thread(target=worker, name="tree-backup", daemon=True).start()

    def prepare(
        self,
        expected_revision: int,
        reason: str,
        operations: list[dict],
        restore_revision: int | None = None,
    ) -> dict:
        with state.TREE_LOCK:
            self.check_baseline()
            self.check_capacity()
            current = self.latest()["id"]
            if current != expected_revision:
                raise ValueError(f"Stale revision: expected {expected_revision}, current {current}")
            if not reason.strip() or len(reason) > 2000:
                raise ValueError("A reason of 1–2000 characters is required")
            before = self.document(current)
            restored = self.document(restore_revision) if restore_revision is not None else None
        if restored is None:
            edited = self.editor.apply(before, operations)
            affected = list(edited.affected_records)
            after = edited.data
        else:
            if operations:
                raise ValueError("Restore cannot be combined with edit operations")
            after = restored
            affected = ["entire tree"]
            operations = [{"op": "restore", "revision": restore_revision}]
        if before == after:
            raise ValueError("Change has no effect")
        # Parse/validate without holding the read lock.
        candidate = projection(after, self.directory)
        token = uuid.uuid4().hex
        difference = self.editor.diff(before, after, None if restored is not None else affected)
        with state.TREE_LOCK, self.db:
            if self.latest()["id"] != current:
                raise ValueError("Tree changed during preparation; prepare again")
            self.db.execute(
                "INSERT INTO proposals VALUES (?,?,?,?,?,?,?)",
                (
                    token,
                    current,
                    reason,
                    json.dumps(operations),
                    digest(after),
                    pack_document(self.db, after, self.editor),
                    json.dumps(affected),
                ),
            )
        return {
            "proposal_id": token,
            "expected_revision": current,
            "sha256": digest(after),
            "affected_records": affected,
            "diff": "\n".join(difference[:1000]),
            "diff_truncated": len(difference) > 1000,
            "counts": {
                "individuals": len(candidate.individuals),
                "families": len(candidate.families),
            },
            "reason": reason,
        }

    def proposal_diff(self, proposal_id: str, offset: int = 0, limit: int = 500) -> dict:
        """Read the complete review diff in bounded pages, including large restores."""
        if offset < 0:
            raise ValueError("Diff offset must be nonnegative")
        row = self.db.execute("SELECT * FROM proposals WHERE token=?", (proposal_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown proposal")
        before = self.document(row["expected"])
        after = unpack_document(self.db, row["document"])
        affected = json.loads(row["affected"])
        lines = self.editor.diff(before, after, None if affected == ["entire tree"] else affected)
        limit = min(max(limit, 1), 1000)
        end = min(offset + limit, len(lines))
        return {
            "proposal_id": proposal_id,
            "offset": offset,
            "total_lines": len(lines),
            "diff": "\n".join(lines[offset:end]),
            "next_offset": end if end < len(lines) else None,
        }

    def apply(self, proposal_id: str, expected_revision: int) -> dict:
        with state.TREE_LOCK:
            previous = self.db.execute(
                "SELECT id FROM revisions WHERE proposal=?", (proposal_id,)
            ).fetchone()
            if previous:
                return {"revision": previous["id"], "already_applied": True}
            proposal = self.db.execute(
                "SELECT * FROM proposals WHERE token=?", (proposal_id,)
            ).fetchone()
            if proposal is None:
                raise ValueError("Unknown proposal")
            if (
                proposal["expected"] != expected_revision
                or self.latest()["id"] != expected_revision
            ):
                raise ValueError("Stale revision; prepare the change again")
            data = unpack_document(self.db, proposal["document"])
            if digest(data) != proposal["digest"]:
                raise ValueError("Proposal checksum mismatch")
        candidate = projection(data, self.directory)
        revision = expected_revision + 1
        with state.TREE_LOCK:
            if self.latest()["id"] != expected_revision:
                previous = self.db.execute(
                    "SELECT id FROM revisions WHERE proposal=?", (proposal_id,)
                ).fetchone()
                if previous:
                    return {"revision": previous["id"], "already_applied": True}
                raise ValueError("Tree changed while building indexes; prepare again")
            self.check_baseline()
            self.check_capacity()
            backup = self.backup()  # Failure aborts before any revision is committed.
            path = immutable_file(
                self.directory / "exports" / f"revision-{revision}-{digest(data)}.ged", data
            )
            with self.db:
                self.db.execute(
                    "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        revision,
                        expected_revision,
                        now(),
                        self.actor,
                        proposal["reason"],
                        proposal["operations"],
                        proposal["digest"],
                        proposal["document"],
                        proposal_id,
                    ),
                )
                self.db.execute("DELETE FROM proposals WHERE expected<?", (revision,))
            self.publish(candidate, path, revision)
            current_backup = None
            backup_error = None
            # Report post-commit failure truthfully, without undoing an accepted revision.
            try:
                current_backup = self.backup()
            except Exception as error:
                backup_error = str(error)
            # Maintenance failure must not turn a committed change into a failed response.
            try:
                self.prune_backups()
                self.prune_exports(path)
            except OSError:
                import logging

                logging.getLogger(__name__).exception("Retention cleanup failed")
        try:
            self.refresh_semantic()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Unable to schedule semantic refresh")
        return {
            "revision": revision,
            "sha256": digest(data),
            "backup": backup,
            "affected_records": json.loads(proposal["affected"]),
            "already_applied": False,
            "current_backup": current_backup,
            "current_backup_error": backup_error,
        }

    def publish(self, candidate, path: Path, revision: int):
        from . import semantic

        for key, place in candidate.places.items():
            old = state.places.get(key)
            if old is not None:
                place.latitude, place.longitude = old.latitude, old.longitude
        for key in INDEXES:
            setattr(state, key, getattr(candidate, key))
        state.HOME_PERSON_ID = candidate.HOME_PERSON_ID
        state.GEDCOM_FILE = path
        self.revision = revision
        # Old snippets must never be returned against the new tree.
        semantic._embeddings = None
        semantic._embedding_ids = []
        semantic._embedding_texts = []

    def refresh_semantic(self):
        from .semantic import refresh_after_write

        refresh_after_write(self.revision)

    def status(self) -> dict:
        self.check_baseline()
        from . import semantic

        return {
            "revision": self.revision,
            "baseline_sha256": self.baseline_hash,
            "semantic_ready": semantic._embeddings is not None,
            "backup_count": len(list((self.directory / "backups").glob("*.sqlite"))),
            "backup_scope": "local only; independent replication must be configured",
            "database_bytes": (self.directory / "tree.sqlite").stat().st_size,
            "total_store_bytes": sum(
                path.stat().st_size for path in self.directory.rglob("*") if path.is_file()
            ),
            "disk_free_bytes": shutil.disk_usage(self.directory).free,
            "baseline_counts": {
                key: int(
                    self.db.execute(
                        "SELECT value FROM metadata WHERE key=?", (f"baseline_{key}",)
                    ).fetchone()[0]
                )
                for key in ("individuals", "families")
            },
        }

    def history(self, limit: int = 20) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT id,parent,created,actor,reason,digest FROM revisions ORDER BY id DESC LIMIT ?",
                (min(max(limit, 1), 100),),
            )
        ]


store: TreeStore | None = None


def initialize_store():
    global store
    if os.getenv("GEDCOM_WRITES_ENABLED", "false").lower() != "true":
        return
    directory = os.getenv("GEDCOM_STORE_DIR")
    if not directory or state.GEDCOM_FILE is None:
        raise ValueError("Writes require GEDCOM_STORE_DIR and GEDCOM_FILE")
    store = TreeStore(
        state.GEDCOM_FILE, Path(directory), os.getenv("GEDCOM_WRITE_ACTOR", "local-operator")
    )
    state.GEDCOM_FILE = store.export(store.revision)
    os.environ["GEDCOM_CACHE_DIR"] = str(store.directory / "cache")
    store.start_daily_backups()


def require_store() -> TreeStore:
    if store is None:
        raise ValueError("Writes are disabled")
    return store
