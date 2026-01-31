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


# Military-related keywords for detecting service
_MILITARY_KEYWORDS = {
    "war",
    "military",
    "army",
    "navy",
    "marine",
    "marines",
    "soldier",
    "regiment",
    "corps",
    "veteran",
    "enlisted",
    "drafted",
    "served",
    "service",
    "wwi",
    "wwii",
    "ww1",
    "ww2",
    "civil war",
    "revolutionary",
    "infantry",
    "cavalry",
    "artillery",
    "battalion",
    "company",
    "brigade",
    "division",
    "air force",
    "airforce",
    "usaf",
    "usmc",
    "usn",
    "coast guard",
    "national guard",
    "pvt",
    "private",
    "corporal",
    "sergeant",
    "lieutenant",
    "captain",
    "major",
    "colonel",
    "general",
    "admiral",
    "seaman",
    "petty officer",
    "combat",
    "battle",
    "campaign",
    "deployment",
    "discharge",
    "honorable",
    "medal",
    "purple heart",
    "bronze star",
    "silver star",
}


def _is_military_event(event: Event) -> bool:
    """Check if an event is military-related."""
    # Check event type
    if event.type in ("MILT", "SERV", "_MILT", "_SERV"):
        return True

    # Check description for military keywords
    description = (event.description or "").lower()
    for keyword in _MILITARY_KEYWORDS:
        if keyword in description:
            return True

    # Check notes for military keywords
    for note in event.notes:
        note_lower = note.lower()
        for keyword in _MILITARY_KEYWORDS:
            if keyword in note_lower:
                return True

    return False


def _get_military_service() -> dict:
    """Find all individuals with military service across the tree.

    Scans all individuals' events for military indicators:
    - Event types: MILT, SERV, EVEN with military description
    - Keywords in description/notes: war, military, army, navy, etc.

    Returns:
        Dict with result_count, individuals list, time_periods, and service_locations
    """
    individuals_with_service: list[dict] = []
    time_periods: dict[str, int] = {}
    location_counts: dict[str, int] = {}

    for indi in state.individuals.values():
        military_events: list[dict] = []

        for event in indi.events:
            if _is_military_event(event):
                event_dict = event.to_dict()
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
