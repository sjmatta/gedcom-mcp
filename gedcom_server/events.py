"""Event-related functions for querying genealogy data."""

import re

from . import state
from .core import _normalize_lookup_id
from .helpers import date_sort_key, extract_year
from .models import Event


def _get_events(individual_id: str) -> list[dict]:
    """Get all events for an individual."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    return [event.to_dict() for event in indi.events]


def _search_events(
    event_type: str | None = None,
    place: str | None = None,
    year: int | None = None,
    year_range: int = 5,
    max_results: int = 50,
) -> list[dict]:
    """Search events by type, place, and/or year."""
    results = []
    place_lower = place.lower() if place else None

    for indi in state.individuals.values():
        for event in indi.events:
            # Filter by event type
            if event_type and event.type != event_type.upper():
                continue

            # Filter by place
            if place_lower and (not event.place or place_lower not in event.place.lower()):
                continue

            # Filter by year
            if year:
                event_year = extract_year(event.date)
                if not event_year or abs(event_year - year) > year_range:
                    continue

            result = event.to_dict()
            result["individual_id"] = indi.id
            result["individual_name"] = indi.full_name()
            results.append(result)

            if len(results) >= max_results:
                return results

    return results


def _get_citations(individual_id: str) -> list[dict]:
    """Get all citations for an individual across all events."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    citations = []
    for event in indi.events:
        for citation in event.citations:
            cite_dict = citation.to_dict()
            cite_dict["event_type"] = event.type
            cite_dict["event_date"] = event.date
            citations.append(cite_dict)

    return citations


def _get_notes(individual_id: str) -> list[dict]:
    """Get all notes for an individual across all events."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    notes = []
    for event in indi.events:
        for note in event.notes:
            notes.append(
                {
                    "event_type": event.type,
                    "event_date": event.date,
                    "note": note,
                }
            )

    return notes


def _person_events(individual_id: str) -> list[dict]:
    """Personal events plus spouse-family events with their owning family ID."""
    indi = state.individuals.get(individual_id)
    if not indi:
        return []
    result = [event.to_dict() for event in indi.events]
    for family_id in dict.fromkeys(indi.families_as_spouse):
        fam = state.families.get(family_id)
        if fam:
            result.extend({**event.to_dict(), "family_id": family_id} for event in fam.events)
    return result


def _get_timeline(individual_id: str) -> list[dict]:
    """Get chronological timeline of events for an individual."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    return sorted(_person_events(lookup_id), key=lambda event: date_sort_key(event.get("date")))


def _get_family_events(family_id: str) -> list[dict]:
    """Get all events for an entire family unit (spouses + children).

    Args:
        family_id: GEDCOM family ID (e.g., "F123" or "@F123@")

    Returns:
        List of events with individual context, sorted chronologically
    """
    lookup_id = _normalize_lookup_id(family_id)
    fam = state.families.get(lookup_id)
    if not fam:
        return []

    events = []

    # Collect all family member IDs
    member_ids = []
    if fam.husband_id:
        member_ids.append(fam.husband_id)
    if fam.wife_id:
        member_ids.append(fam.wife_id)
    member_ids.extend(fam.children_ids)

    # Collect events from all members
    for member_id in member_ids:
        indi = state.individuals.get(member_id)
        if indi:
            for event in indi.events:
                event_dict = event.to_dict()
                event_dict["individual_id"] = indi.id
                event_dict["individual_name"] = indi.full_name()
                events.append(event_dict)

    events.extend(
        {**event.to_dict(), "family_id": fam.id, "individual_id": None} for event in fam.events
    )
    events.sort(key=lambda event: date_sort_key(event.get("date")))
    return events


def _get_events_batch(individual_ids: list[str]) -> dict[str, list[dict]]:
    """Get events for multiple individuals in one call.

    Args:
        individual_ids: List of GEDCOM IDs to retrieve events for

    Returns:
        Dict mapping each ID → list of events (empty list if not found)
    """
    results: dict[str, list[dict]] = {}
    for id_str in individual_ids:
        lookup_id = _normalize_lookup_id(id_str)
        indi = state.individuals.get(lookup_id)
        if indi:
            results[lookup_id] = [event.to_dict() for event in indi.events]
        else:
            results[lookup_id] = []
    return results


def _get_family_timeline(
    individual_ids: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict]:
    """Create merged timeline across multiple individuals.

    Args:
        individual_ids: List of GEDCOM IDs to include
        start_year: Optional filter for earliest year
        end_year: Optional filter for latest year

    Returns:
        List of events with individual context, sorted chronologically
    """
    events = []

    for id_str in individual_ids:
        lookup_id = _normalize_lookup_id(id_str)
        indi = state.individuals.get(lookup_id)
        if indi:
            for event in indi.events:
                event_year = extract_year(event.date)

                # Apply year filters
                if start_year and event_year and event_year < start_year:
                    continue
                if end_year and event_year and event_year > end_year:
                    continue

                event_dict = event.to_dict()
                event_dict["individual_id"] = indi.id
                event_dict["individual_name"] = indi.full_name()
                events.append(event_dict)

    family_ids = {
        family_id
        for id_str in individual_ids
        if (indi := state.individuals.get(_normalize_lookup_id(id_str)))
        for family_id in indi.families_as_spouse
    }
    for family_id in sorted(family_ids):
        fam = state.families.get(family_id)
        if fam:
            for event in fam.events:
                year = extract_year(event.date)
                if year and ((start_year and year < start_year) or (end_year and year > end_year)):
                    continue
                events.append({**event.to_dict(), "family_id": family_id, "individual_id": None})
    events.sort(key=lambda event: date_sort_key(event.get("date")))
    return events


# Explicit records are stronger evidence than contextual references in prose.
_MILITARY_PATTERN = re.compile(
    r"\b(?:military|army|navy|marines?|soldiers?|regiments?|veterans?|"
    r"enlisted|drafted|infantry|cavalry|artillery|battalion|brigade|"
    r"air[ -]?force|usaf|usmc|usn|coast guard|national guard|"
    r"civil war|revolutionary war|world war(?: [12i]+)?|ww[12i]+|"
    r"purple heart|bronze star|silver star)\b",
    re.IGNORECASE,
)


def _military_evidence(event: Event) -> dict | None:
    """Explain explicit service records or possible military references.

    A keyword in a note is a research lead, not proof that its subject served.
    Broad terms such as 'general', 'private', and 'service' are insufficient.
    """
    if event.type.upper() in ("MILT", "SERV", "_MILT", "_SERV"):
        return {"basis": "explicit_tag", "matched_text": event.type}
    for text in [event.description or "", *event.notes]:
        match = _MILITARY_PATTERN.search(text)
        if match:
            return {"basis": "possible_reference", "matched_text": match.group(0)}
    return None


def _is_military_event(event: Event) -> bool:
    """Whether an event has explicit or contextual military evidence."""
    return _military_evidence(event) is not None


def _get_military_service() -> dict:
    """Find explicit military records and possible military references.

    Scans individual events for military tags and contextual phrases in notes
    or descriptions. Each event reports its evidence basis; references in prose
    do not establish that the individual served.

    Returns:
        Dict with result_count, individuals list, time_periods, and service_locations
    """
    individuals_with_service: list[dict] = []
    time_periods: dict[str, int] = {}
    location_counts: dict[str, int] = {}

    for indi in state.individuals.values():
        military_events: list[dict] = []

        for event in indi.events:
            evidence = _military_evidence(event)
            if evidence:
                event_dict = event.to_dict()
                event_dict["military_evidence"] = evidence
                military_events.append(event_dict)

                # Track time period
                year = extract_year(event.date)
                if year:
                    century = (year // 100) * 100
                    period = f"{century}s"
                    time_periods[period] = time_periods.get(period, 0) + 1

                # Track location
                if event.place:
                    location_counts[event.place] = location_counts.get(event.place, 0) + 1

        if military_events:
            individuals_with_service.append(
                {
                    "id": indi.id,
                    "name": indi.full_name(),
                    "birth_date": indi.birth_date,
                    "death_date": indi.death_date,
                    "military_events": military_events,
                }
            )

    # Sort locations by count
    top_locations = sorted(location_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "result_count": len(individuals_with_service),
        "individuals": individuals_with_service,
        "time_periods": dict(sorted(time_periods.items())),
        "service_locations": [{"place": p, "count": c} for p, c in top_locations],
    }
