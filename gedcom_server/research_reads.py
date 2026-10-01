"""Bounded evidence reads against one current, lossless GEDCOM snapshot."""

import hashlib
from collections import defaultdict

from ged4py.date import DateValue

from . import state, writes
from .constants import EVENT_TAGS, FAMILY_EVENT_TAGS
from .core import _get_individuals_batch, _normalize_lookup_id
from .document import Document
from .helpers import date_sort_key
from .sources import _get_source


class Snapshot:
    def __init__(self, expected_snapshot=None):
        store = writes.store
        self.revision = store.revision if store else None
        if store:
            data = store.document(store.revision)
        elif state.GEDCOM_FILE is not None:
            data = state.GEDCOM_FILE.read_bytes()
        else:
            raise ValueError("Tree is not initialized")
        self.token = hashlib.sha256(data).hexdigest()
        if expected_snapshot is not None and expected_snapshot != self.token:
            raise ValueError("Tree changed; restart pagination")
        self.doc = Document(data)
        self.records = {}
        self.paths: dict[int, list[dict]] = {}
        stack: list[tuple[int, list[dict], dict]] = []
        for pos, line in enumerate(self.doc.lines):
            if line.level == 0:
                stack = [(0, [], defaultdict(int))]
                if line.xref:
                    self.records[line.xref] = pos
                self.paths[pos] = []
                continue
            while stack[-1][0] >= line.level:
                stack.pop()
            _, parent_path, counts = stack[-1]
            path = parent_path + [{"tag": line.tag, "index": counts[line.tag]}]
            counts[line.tag] += 1
            self.paths[pos] = path
            stack.append((line.level, path, defaultdict(int)))

    def fields(self, start, end=None):
        end = self.doc.end(start) if end is None else end
        return [
            {
                "path": self.paths[pos],
                "tag": line.tag,
                "value": line.value,
                "level": line.level,
                "raw": line.raw,
            }
            for pos in range(start, end)
            for line in [self.doc.lines[pos]]
        ]

    def page(self, items, offset, limit):
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("Use nonnegative offset and limit between 1 and 500")
        return {
            "snapshot": self.token,
            "revision": self.revision,
            "total": len(items),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(items) else None,
            "items": items[offset : offset + limit],
        }


def get_record(record_id, path=None, expected_snapshot=None, offset=0, limit=100):
    snap = Snapshot(expected_snapshot)
    record_id = _normalize_lookup_id(record_id)
    start = snap.doc.locate(record_id, path or [])
    result = snap.page(snap.fields(start), offset, limit)
    return {
        **result,
        "record_id": record_id,
        "selected_path": path or [],
        "raw": "".join(field["raw"] for field in result["items"]),
    }


def get_source(source_id):
    source = _get_source(source_id)
    if source is None:
        return None
    repo = state.repositories.get(source.get("repository_id") or "")
    repository = repo.to_dict() if repo else None
    if repo:
        snap = Snapshot()
        start = snap.records.get(repo.id)
        if start is not None:
            fields = snap.fields(start)
            # ged4py treats NAME as a personal name even on REPO records.
            # Read the repository's literal name instead of that tuple projection.
            repository = {
                **repo.to_dict(),
                "name": next(
                    (f["value"] for f in fields if f["tag"] == "NAME" and len(f["path"]) == 1),
                    repo.name,
                ),
                "fields": fields,
            }
    return {**source, "repository": repository}


def search_sources(query, expected_snapshot=None, offset=0, limit=100):
    snap = Snapshot(expected_snapshot)
    items = [
        source.to_dict()
        for _, source in sorted(state.sources.items())
        if query.casefold()
        in " ".join(
            filter(None, [source.title, source.author, source.publication, source.note])
        ).casefold()
    ]
    return snap.page(items, offset, limit)


def get_source_references(source_id, page=None, expected_snapshot=None, offset=0, limit=100):
    snap = Snapshot(expected_snapshot)
    source_id = _normalize_lookup_id(source_id)
    if source_id not in snap.records or snap.doc.lines[snap.records[source_id]].tag != "SOUR":
        raise ValueError("Source not found")
    items = []
    for owner, start in snap.records.items():
        for pos in range(start + 1, snap.doc.end(start)):
            line = snap.doc.lines[pos]
            if line.tag != "SOUR" or line.value != source_id:
                continue
            fields = snap.fields(pos)
            pages = [f["value"] for f in fields if f["tag"] == "PAGE"]
            if page is not None and page not in pages:
                continue
            path = snap.paths[pos]
            items.append(
                {
                    "record_id": owner,
                    "record_type": snap.doc.lines[start].tag,
                    "path": path,
                    "fact_path": path[:-1],
                    "pages": pages,
                    "fields": fields,
                    "raw": "".join(f["raw"] for f in fields),
                }
            )
    return snap.page(items, offset, limit)


def year_interval(text):
    """Calendar years; approximation uses its nominal year, never an invented window."""
    try:
        date = DateValue.parse(text)
        kind = date.kind.name
        if kind == "PHRASE":
            return None, None, kind
        first, last = date.key()
        # Non-European calendar years cannot be compared to Gregorian year filters.
        if first.calendar.value not in ("GREGORIAN", "JULIAN") or last.calendar.value not in (
            "GREGORIAN",
            "JULIAN",
        ):
            return None, None, kind
        lower: int | None = -first.year if first.bc else first.year
        upper: int | None = -last.year if last.bc else last.year
        if kind in ("BEFORE", "TO"):
            lower = None
        if kind in ("AFTER", "FROM"):
            upper = None
        return lower, upper, kind
    except ValueError, TypeError, AttributeError:
        return None, None, "UNKNOWN"


def events(snap, individual_ids=None):
    scope = None if individual_ids is None else {_normalize_lookup_id(i) for i in individual_ids}
    if scope is not None:
        missing = scope - state.individuals.keys()
        if missing:
            raise ValueError(f"Individuals not found: {sorted(missing)}")
    for owner, start in snap.records.items():
        record_type = snap.doc.lines[start].tag
        if record_type == "INDI":
            if scope is not None and owner not in scope:
                continue
            tags = set(EVENT_TAGS)
            participants = [owner]
        elif record_type == "FAM":
            family = state.families.get(owner)
            participants = [p for p in (family.husband_id, family.wife_id) if p] if family else []
            if scope is not None and not scope.intersection(participants):
                continue
            tags = FAMILY_EVENT_TAGS
        else:
            continue
        for pos in range(start + 1, snap.doc.end(start)):
            line = snap.doc.lines[pos]
            if line.level != 1 or line.tag not in tags:
                continue
            fields = snap.fields(pos)
            direct = {f["tag"]: f["value"] for f in fields[1:] if f["level"] == 2}
            date = direct.get("DATE")
            lower, upper, kind = year_interval(date)
            yield {
                "record_id": owner,
                "record_type": record_type,
                "path": snap.paths[pos],
                "type": line.tag,
                "description": line.value,
                "date": date,
                "place": direct.get("PLAC"),
                "participant_ids": participants,
                "year_interval": {"start": lower, "end": upper, "kind": kind},
                "fields": fields,
            }


def search_events(
    event_type=None,
    place=None,
    start_year=None,
    end_year=None,
    individual_ids=None,
    include_undated=False,
    expected_snapshot=None,
    offset=0,
    limit=100,
):
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("start_year must not exceed end_year")
    if individual_ids is not None and len(individual_ids) > 500:
        raise ValueError("At most 500 individual IDs per call")
    snap = Snapshot(expected_snapshot)
    items = []
    for event in events(snap, individual_ids):
        if event_type and event["type"] != event_type.upper():
            continue
        if place and place.casefold() not in (event["place"] or "").casefold():
            continue
        interval = event["year_interval"]
        if start_year is not None or end_year is not None:
            if interval["start"] is None and interval["end"] is None:
                if not include_undated:
                    continue
            elif (
                start_year is not None
                and interval["end"] is not None
                and interval["end"] < start_year
            ) or (
                end_year is not None
                and interval["start"] is not None
                and interval["start"] > end_year
            ):
                continue
        items.append(event)
    items.sort(key=lambda e: (date_sort_key(e["date"]), e["record_id"], str(e["path"])))
    return snap.page(items, offset, limit)


def get_group_timeline(
    individual_ids,
    start_year=None,
    end_year=None,
    include_undated=False,
    expected_snapshot=None,
    offset=0,
    limit=100,
):
    return search_events(
        start_year=start_year,
        end_year=end_year,
        individual_ids=individual_ids,
        include_undated=include_undated,
        expected_snapshot=expected_snapshot,
        offset=offset,
        limit=limit,
    )


def get_individuals_batch(individual_ids):
    if len(individual_ids) > 500:
        raise ValueError("At most 500 individual IDs per call")
    return _get_individuals_batch(individual_ids)
