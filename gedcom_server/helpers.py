"""Utility functions for GEDCOM parsing and data manipulation."""

import hashlib
import re

import geonamescache
from ged4py.date import DateValue

from .constants import PLACE_ABBREVIATIONS
from .models import Place

# Lazy-loaded geonamescache instance
_gc: geonamescache.GeonamesCache | None = None


def extract_year(date_str: str | None) -> int | None:
    """Extract year from a GEDCOM date string."""
    if not date_str:
        return None
    match = re.search(r"\b(\d{4})\b", date_str)
    return int(match.group(1)) if match else None


def normalize_id(ref) -> str | None:
    """Normalize a GEDCOM reference to a consistent ID string with @ symbols."""
    if ref is None:
        return None
    if hasattr(ref, "xref_id"):
        return ref.xref_id
    s = str(ref)
    if not s:
        return None
    # Ensure consistent format with @ symbols
    stripped = s.strip("@")
    return f"@{stripped}@" if stripped else None


def get_record_value(record, tag: str) -> str | None:
    """Get value from a ged4py record by tag."""
    try:
        sub = record.sub_tag(tag)
        if sub and sub.value:
            return str(sub.value)
    except AttributeError, KeyError:
        pass
    return None


def get_event_details(record, event_tag: str) -> tuple[str | None, str | None]:
    """Get date and place from an event record."""
    date_val = None
    place_val = None
    try:
        event = record.sub_tag(event_tag)
        if event:
            date_sub = event.sub_tag("DATE")
            if date_sub and date_sub.value:
                date_val = str(date_sub.value)
            place_sub = event.sub_tag("PLAC")
            if place_sub and place_sub.value:
                place_val = str(place_sub.value)
    except AttributeError, KeyError:
        pass
    return date_val, place_val


def normalize_place_string(place: str) -> str:
    """Normalize a place string for matching.

    Applies lowercasing, abbreviation expansion, and whitespace cleanup.
    """
    result = place.lower().strip()

    # Expand abbreviations
    for abbr, full in PLACE_ABBREVIATIONS.items():
        result = re.sub(r"(?<!\w)" + re.escape(abbr) + r"(?!\w)", full, result)

    # Collapse whitespace
    result = " ".join(result.split())

    return result


def parse_place_components(place: str) -> list[str]:
    """Parse place string into components (typically: city, county, state, country)."""
    # GEDCOM places are comma-separated, from most specific to least
    components = [c.strip() for c in place.split(",") if c.strip()]
    return components


def get_place_id(place: str) -> str:
    """Generate a unique ID for a place based on its normalized form."""
    normalized = normalize_place_string(place)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def create_place(place_str: str) -> Place:
    """Create a Place object from a place string."""
    place_id = get_place_id(place_str)
    normalized = normalize_place_string(place_str)
    components = parse_place_components(place_str)

    return Place(
        id=place_id,
        original=place_str,
        normalized=normalized,
        components=components,
    )


def _get_geonames_cache() -> geonamescache.GeonamesCache:
    """Get or create the geonamescache instance."""
    global _gc
    if _gc is None:
        _gc = geonamescache.GeonamesCache()
    return _gc


def geocode_place_coords(place_normalized: str) -> tuple[float, float] | None:
    """Get lat/lon for a normalized place name using geonamescache.

    Tries to match city first, then country.
    """
    from .geocoding import local_geocode

    return local_geocode(place_normalized)[0]


def date_sort_key(date_str: str | None) -> DateValue:
    """Order GEDCOM dates/ranges with undated phrases last; preserve source text.

    Ordering an approximate date is a display convention, not an assertion of
    its exact day. ged4py handles partial dates, qualifiers, and calendars.
    """
    try:
        return DateValue.parse(date_str)
    except ValueError, TypeError:
        return DateValue.parse(None)
