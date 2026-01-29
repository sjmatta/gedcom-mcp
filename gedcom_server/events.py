"""Event-related functions for querying genealogy data."""

from . import state
from .core import _normalize_lookup_id
from .helpers import extract_year
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


def _get_timeline(individual_id: str) -> list[dict]:
    """Get chronological timeline of events for an individual."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    # Sort events by date (events without dates come last)
    def sort_key(event: Event) -> tuple[int, str]:
        year = extract_year(event.date)
        # Put events without years at the end, sort by year then by date string
        return (year if year else 9999, event.date or "")

    sorted_events = sorted(indi.events, key=sort_key)
    return [event.to_dict() for event in sorted_events]


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

    # Sort by date
    def sort_key(e: dict) -> tuple[int, str]:
        year = extract_year(e.get("date"))
        return (year if year else 9999, e.get("date") or "")

    events.sort(key=sort_key)
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

    # Sort by date
    def sort_key(e: dict) -> tuple[int, str]:
        year = extract_year(e.get("date"))
        return (year if year else 9999, e.get("date") or "")

    events.sort(key=sort_key)
    return events
