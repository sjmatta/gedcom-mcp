"""Append-only research ledger: hypotheses, evidence and verdicts beside the tree.

Entries never change the family tree, so they need no proposal or approval. They
live in the revision store's SQLite database and are covered by its backups.
"""

import json
import uuid
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from . import state
from .change_models import FieldPath, OperationModel
from .core import _normalize_lookup_id
from .revision_storage import now

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_entries (
 id INTEGER PRIMARY KEY, hypothesis_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK (kind IN ('hypothesis', 'evidence', 'verdict')),
 created TEXT NOT NULL, actor TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_entries_hypothesis ON research_entries(hypothesis_id, id);
CREATE TRIGGER IF NOT EXISTS immutable_research_update BEFORE UPDATE ON research_entries
 BEGIN SELECT RAISE(ABORT, 'research entries are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_research_delete BEFORE DELETE ON research_entries
 BEGIN SELECT RAISE(ABORT, 'research entries are append-only'); END;
"""

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Likelihood = Literal[
    "almost_no_chance",
    "very_unlikely",
    "unlikely",
    "roughly_even",
    "likely",
    "very_likely",
    "almost_certain",
]


class Locator(OperationModel):
    """Where the evidence is: a tree record/path, a source, a URL, or a description."""

    record_id: str | None = None
    path: list[FieldPath] = Field(default_factory=list)
    source_id: str | None = None
    page: str = ""
    url: str = ""
    description: str = ""

    @model_validator(mode="after")
    def locatable(self):
        if not (self.record_id or self.source_id or self.url or self.description):
            raise ValueError("Locator needs record_id, source_id, url or description")
        return self


class HypothesisEntry(OperationModel):
    kind: Literal["hypothesis"]
    statement: Text
    subjects: list[str] = Field(min_length=1, max_length=50)
    rivals: list[Text] = Field(min_length=1, max_length=10)
    predictions: list[Text] = Field(min_length=1, max_length=20)
    origin: Literal["random_walk", "research_gap", "audit", "user_request", "other"] = "other"


class EvidenceEntry(OperationModel):
    kind: Literal["evidence"]
    hypothesis_id: str
    stance: Literal["supports", "refutes", "qualifies", "context"]
    source_type: Literal["original", "derivative", "authored", "unknown"]
    information_type: Literal["primary", "secondary", "undetermined"]
    evidence_type: Literal["direct", "indirect", "negative"]
    locator: Locator
    excerpt: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=4000)


class VerdictEntry(OperationModel):
    kind: Literal["verdict"]
    hypothesis_id: str
    status: Literal["supported", "refuted", "inconclusive", "withdrawn"]
    likelihood: Likelihood | None = None
    confidence: Literal["low", "moderate", "high"]
    argument: Text
    disconfirmation_search: Text
    would_change_if: str = Field(default="", max_length=4000)
    proposal_id: str | None = None


ResearchEntry = Annotated[
    HypothesisEntry | EvidenceEntry | VerdictEntry, Field(discriminator="kind")
]
_ENTRY: TypeAdapter[HypothesisEntry | EvidenceEntry | VerdictEntry] = TypeAdapter(ResearchEntry)


def _rows(store, hypothesis_id):
    return store.db.execute(
        "SELECT * FROM research_entries WHERE hypothesis_id=? ORDER BY id", (hypothesis_id,)
    ).fetchall()


def record(store, entry) -> dict:
    """Validate and append one entry; returns the stored entry with its hypothesis id."""
    entry = _ENTRY.validate_python(entry)
    with state.TREE_LOCK:
        if isinstance(entry, HypothesisEntry):
            subjects = [_normalize_lookup_id(s) for s in entry.subjects]
            if missing := [s for s in subjects if s not in state.individuals]:
                raise ValueError(f"Unknown subjects: {', '.join(missing)}")
            entry = entry.model_copy(update={"subjects": subjects})
            hypothesis_id = f"hyp_{uuid.uuid4().hex[:12]}"
        else:
            hypothesis_id = entry.hypothesis_id
            rows = _rows(store, hypothesis_id)
            if not rows or rows[0]["kind"] != "hypothesis":
                raise ValueError("Unknown hypothesis_id; record the hypothesis first")
            if (
                isinstance(entry, VerdictEntry)
                and entry.status in {"supported", "refuted"}
                and not any(row["kind"] == "evidence" for row in rows)
            ):
                raise ValueError("A supported or refuted verdict needs recorded evidence")
        body = entry.model_dump(mode="json", exclude={"hypothesis_id"})
        with store.db:
            cursor = store.db.execute(
                "INSERT INTO research_entries"
                " (hypothesis_id, kind, created, actor, revision, body) VALUES (?,?,?,?,?,?)",
                (hypothesis_id, entry.kind, now(), store.actor, store.revision, json.dumps(body)),
            )
    return {"entry_id": cursor.lastrowid, "hypothesis_id": hypothesis_id, **body}


def _hypothesis(rows) -> dict:
    head = json.loads(rows[0]["body"])
    entries = [
        {
            "entry_id": row["id"],
            "created": row["created"],
            "actor": row["actor"],
            "revision": row["revision"],
            **json.loads(row["body"]),
        }
        for row in rows
    ]
    verdicts = [e for e in entries if e["kind"] == "verdict"]
    return {
        "hypothesis_id": rows[0]["hypothesis_id"],
        "statement": head["statement"],
        "subjects": head["subjects"],
        "status": verdicts[-1]["status"] if verdicts else "open",
        "created": rows[0]["created"],
        "updated": rows[-1]["created"],
        "evidence_count": sum(e["kind"] == "evidence" for e in entries),
        "entries": entries,
    }


def read(store, hypothesis_id=None, individual_id=None, status=None, offset=0, limit=20) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Use nonnegative offset and limit between 1 and 100")
    subject = _normalize_lookup_id(individual_id) if individual_id else None
    with state.TREE_LOCK:
        query = "SELECT hypothesis_id FROM research_entries WHERE kind='hypothesis'"
        args: tuple = ()
        if hypothesis_id:
            query, args = query + " AND hypothesis_id=?", (hypothesis_id,)
        ids = [row[0] for row in store.db.execute(query + " ORDER BY id DESC", args)]
        items = [_hypothesis(_rows(store, hid)) for hid in ids]
    items = [
        item
        for item in items
        if (subject is None or subject in item["subjects"])
        and (status is None or item["status"] == status)
    ]
    return {
        "total": len(items),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(items) else None,
        "items": items[offset : offset + limit],
        "note": "Ledger entries record research reasoning; they are not tree facts.",
    }
