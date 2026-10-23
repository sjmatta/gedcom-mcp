"""Scoped research gaps around a person's ancestry; suggestions, never conclusions."""

import re
from collections import deque

from . import state
from .core import _normalize_lookup_id
from .helpers import normalize_place_string
from .interface_reads import snapshot_metadata
from .relationships import parent_links

# Lower rank sorts first within a generation: ambiguity and conflicts before absences.
KINDS = {
    "ambiguous_parents": (1, "Several usable parent families; none is selected"),
    "conflicting_vital": (2, "Different recorded {event} structures disagree"),
    "missing_parent": (3, "Parent family records only one parent"),
    "no_recorded_parents": (3, "No parent family is recorded in this tree"),
    "only_disproven_parents": (3, "Every recorded parent link is marked disproven"),
    "dangling_parent_family": (3, "A parent-family pointer names a missing family"),
    "uncited_vital": (4, "{event} has no source citation"),
    "no_birth_record": (5, "No birth or baptism event is recorded"),
}
NEXT_READ = {
    "ambiguous_parents": "get_people(view='record') and get_parent_families to compare the claims",
    "conflicting_vital": "get_record(individual_id) to compare the alternate structures and citations",
    "missing_parent": "get_record(family_id) and get_timeline for the recorded parent",
    "no_recorded_parents": "get_timeline and external records near the birth date and place",
    "only_disproven_parents": "get_record(individual_id) to read why the links were disproven",
    "dangling_parent_family": "audit_tree; the pointer needs a structural repair",
    "uncited_vital": "get_record(individual_id, path) and search_sources for a matching source",
    "no_birth_record": "search_events near the person's earliest recorded event",
}
MONTHS = re.compile(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b")


def _date(value):
    """Formatting-insensitive date text: '(31 January 1930)' equals '31 JAN 1930'."""
    text = MONTHS.sub(r"\1", (value or "").upper().replace("(", " ").replace(")", " "))
    return " ".join(text.split())


US_STATES = {
    "al": "alabama",
    "ak": "alaska",
    "az": "arizona",
    "ar": "arkansas",
    "ca": "california",
    "co": "colorado",
    "ct": "connecticut",
    "de": "delaware",
    "fl": "florida",
    "ga": "georgia",
    "hi": "hawaii",
    "id": "idaho",
    "il": "illinois",
    "in": "indiana",
    "ia": "iowa",
    "ks": "kansas",
    "ky": "kentucky",
    "la": "louisiana",
    "me": "maine",
    "md": "maryland",
    "ma": "massachusetts",
    "mi": "michigan",
    "mn": "minnesota",
    "ms": "mississippi",
    "mo": "missouri",
    "mt": "montana",
    "ne": "nebraska",
    "nv": "nevada",
    "nh": "new hampshire",
    "nj": "new jersey",
    "nm": "new mexico",
    "ny": "new york",
    "nc": "north carolina",
    "nd": "north dakota",
    "oh": "ohio",
    "ok": "oklahoma",
    "or": "oregon",
    "pa": "pennsylvania",
    "ri": "rhode island",
    "sc": "south carolina",
    "sd": "south dakota",
    "tn": "tennessee",
    "tx": "texas",
    "ut": "utah",
    "vt": "vermont",
    "va": "virginia",
    "wa": "washington",
    "wv": "west virginia",
    "wi": "wisconsin",
    "wy": "wyoming",
    "dc": "district of columbia",
}


def _place(value):
    # Local to gap detection: changing the shared normalizer would change place IDs.
    # Only the last word is expanded, where a US state code sits ("Pittsburgh, PA").
    words = normalize_place_string(value or "").replace(",", " ").split()
    if words:
        words[-1] = US_STATES.get(words[-1], words[-1])
    return " ".join(words)


def _conflicting(values):
    """True when two values disagree; a less specific value contained in another agrees."""
    tokens = [set(value.split()) for value in values]
    return any(not (a <= b or b <= a) for i, a in enumerate(tokens) for b in tokens[i + 1 :])


VITALS = {
    "BIRT": "Birth",
    "CHR": "Christening",
    "BAPM": "Baptism",
    "DEAT": "Death",
    "BURI": "Burial",
}


def research_gaps(individual_id=None, generations=4, offset=0, limit=50, expected_snapshot=None):
    if not 0 <= generations <= 10:
        raise ValueError("generations must be between 0 and 10")
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("Use nonnegative offset and limit between 1 and 200")
    meta = snapshot_metadata(expected_snapshot)
    root = _normalize_lookup_id(individual_id) if individual_id else state.HOME_PERSON_ID
    if not root or root not in state.individuals:
        raise ValueError("Unknown individual; provide individual_id or configure a home person")

    gaps = []
    generation = {root: 0}
    queue = deque([root])
    depth_limited = 0

    def gap(kind, person, gen, **detail):
        rank, reason = KINDS[kind]
        gaps.append(
            {
                "kind": kind,
                "individual": state.individuals[person].to_summary(),
                "generation": gen,
                "reason": reason.format(**detail),
                "next_read": NEXT_READ[kind],
                **{key: value for key, value in detail.items() if key != "event"},
                "_rank": (gen, rank),
            }
        )

    while queue:
        person = queue.popleft()
        gen = generation[person]
        indi = state.individuals[person]
        links = parent_links(person, "all")
        recorded = indi.parent_families or links
        parents = []
        if indi.parent_selection == "ambiguous":
            gap("ambiguous_parents", person, gen, family_ids=[link.family_id for link in links])
        elif not recorded:
            gap("no_recorded_parents", person, gen)
        elif not links:
            gap("only_disproven_parents", person, gen)
        for link in parent_links(person):
            family = state.families.get(link.family_id)
            if family is None:
                gap("dangling_parent_family", person, gen, family_id=link.family_id)
                continue
            present = [pid for pid in (family.husband_id, family.wife_id) if pid]
            if len(present) == 1:
                gap("missing_parent", person, gen, family_id=family.id)
            parents += [pid for pid in present if pid in state.individuals]

        signatures: dict[str, tuple[set, set]] = {}
        for event in indi.events:
            if event.type not in VITALS:
                continue
            dates, places = signatures.setdefault(event.type, (set(), set()))
            dates.update({_date(event.date)} - {""})  # a missing value is not a conflict
            places.update({_place(event.place)} - {""})
            if not event.citations and event.type in {"BIRT", "DEAT"}:
                gap("uncited_vital", person, gen, event=VITALS[event.type], event_type=event.type)
        for tag, (dates, places) in signatures.items():
            differs = [
                name
                for name, values in (("date", dates), ("place", places))
                if _conflicting(values)
            ]
            if differs:
                gap(
                    "conflicting_vital",
                    person,
                    gen,
                    event=VITALS[tag],
                    event_type=tag,
                    differs=differs,
                )
        if not ({"BIRT", "CHR", "BAPM"} & signatures.keys()) and not indi.birth_date:
            gap("no_birth_record", person, gen)

        unseen = [pid for pid in parents if pid not in generation]
        if gen < generations:
            for pid in unseen:
                generation[pid] = gen + 1
                queue.append(pid)
        elif unseen:
            depth_limited += 1

    gaps.sort(key=lambda item: (*item["_rank"], item["individual"]["id"], item["kind"]))
    for item in gaps:
        del item["_rank"]
    return {
        **meta,
        "root": state.individuals[root].to_summary(),
        "generations": generations,
        "people_examined": len(generation),
        "depth_limited_people": depth_limited,
        "ordering": "Nearest generation first; then ambiguity, conflicts, missing parents, citations",
        "note": "A gap means this tree lacks the record, not that no record exists.",
        "total": len(gaps),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(gaps) else None,
        "items": gaps[offset : offset + limit],
    }
