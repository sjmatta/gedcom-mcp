"""Geospatial search for GEDCOM genealogy data.

Provides two search modes:
1. proximity (default): Find individuals with events within X miles of a point
2. within: Find individuals with events inside a region's bounding box

Geocoding uses three tiers:
1. GEDCOM places - match against places already in your tree
2. geonamescache - local database of ~25K major cities
3. Nominatim (OpenStreetMap) - best coverage, rate limited to 1 req/sec
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from haversine import Unit, haversine
from rapidfuzz import fuzz, process

from . import state
from .helpers import (
    _get_geonames_cache,
    get_place_id,
    normalize_place_string,
    parse_place_components,
)

if TYPE_CHECKING:
    from .models import Place

logger = logging.getLogger(__name__)

# Rate limiting for Nominatim (1 request per second)
_last_nominatim_request: float = 0.0
_nominatim_lock = threading.Lock()

# Geocoding progress (thread-safe)
_geocoding_lock = threading.Lock()
_geocoding_progress: dict = {
    "status": "not_started",  # "not_started" | "running" | "complete" | "disabled"
    "total": 0,
    "geocoded": 0,
    "pending": 0,
    "percent": 0,
}

# Cache for Nominatim results (persisted to disk)
_geocache: dict[str, dict] = {}  # place_id -> {lat, lon, source, confidence}
_geocache_dirty = False

# Bounding box threshold to distinguish regions from cities (in degrees)
# A bounding box spanning more than this is considered a "region"
_REGION_BBOX_THRESHOLD = 0.5  # ~35 miles at mid-latitudes


def is_enabled() -> bool:
    """Check if GIS search is enabled via environment variable."""
    return os.getenv("GIS_SEARCH_ENABLED", "true").lower() == "true"


def get_geocoding_status() -> dict:
    """Get current geocoding progress."""
    with _geocoding_lock:
        return dict(_geocoding_progress)


def _get_cache_path() -> Path | None:
    """Get path for geocoding cache file based on GEDCOM file location."""
    if state.GEDCOM_FILE is None:
        return None
    return state.GEDCOM_FILE.with_suffix(".geocache.json")


def _compute_gedcom_hash() -> str:
    """Compute SHA256 hash of the GEDCOM file for cache invalidation."""
    if state.GEDCOM_FILE is None:
        return ""
    sha256 = hashlib.sha256()
    with open(state.GEDCOM_FILE, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _load_geocache() -> bool:
    """Load geocoding cache from disk if valid. Returns True on success."""
    global _geocache

    cache_path = _get_cache_path()
    if cache_path is None or not cache_path.exists():
        return False

    try:
        with open(cache_path) as f:
            data = json.load(f)

        # Validate cache
        cached_hash = data.get("gedcom_hash", "")
        current_hash = _compute_gedcom_hash()
        if cached_hash != current_hash:
            logger.info("Geocache invalidated: GEDCOM file changed")
            return False

        # Load geocoded places
        _geocache = data.get("geocoded", {})
        logger.info(f"Loaded {len(_geocache)} geocoded places from cache")
        return True
    except Exception as e:
        logger.warning(f"Failed to load geocache: {e}")
        return False


def _save_geocache() -> None:
    """Persist geocoding cache to disk."""
    global _geocache_dirty

    cache_path = _get_cache_path()
    if cache_path is None:
        return

    try:
        data = {
            "gedcom_hash": _compute_gedcom_hash(),
            "geocoded": _geocache,
        }
        with open(cache_path, "w") as f:
            json.dump(data, f)
        _geocache_dirty = False
        logger.info(f"Saved geocache with {len(_geocache)} places to {cache_path}")
    except Exception as e:
        logger.warning(f"Failed to save geocache: {e}")


def _is_ungeocodable(place_str: str) -> bool:
    """Check if a place is inherently un-geocodable."""
    lower = place_str.lower().strip()
    ungeocodable = {
        "at sea",
        "on ship",
        "in transit",
        "unknown",
        "?",
        "",
        "n/a",
        "na",
        "none",
    }
    return lower in ungeocodable


def _geocode_via_geonamescache(
    place_normalized: str,
) -> tuple[tuple[float, float] | None, str]:
    """Geocode using geonamescache with fuzzy matching.

    Returns (coords, confidence) where confidence is "high", "medium", or "low".
    """
    gc = _get_geonames_cache()
    components = parse_place_components(place_normalized)

    if not components:
        return None, "low"

    city_name = components[0].lower()
    cities = gc.get_cities()

    # Try exact city match first (high confidence)
    for city in cities.values():
        if city["name"].lower() == city_name:
            return (city["latitude"], city["longitude"]), "high"

    # Try fuzzy match on city name (medium confidence)
    city_names = {cid: c["name"].lower() for cid, c in cities.items()}
    matches = process.extract(
        city_name,
        city_names.values(),
        scorer=fuzz.ratio,
        limit=3,
        score_cutoff=85,
    )

    if matches:
        best_match = matches[0][0]
        for cid, name in city_names.items():
            if name == best_match:
                city = cities[cid]
                return (city["latitude"], city["longitude"]), "medium"

    return None, "low"


def _geocode_via_nominatim(
    place_str: str,
) -> tuple[tuple[float, float] | None, str]:
    """Geocode using OpenStreetMap Nominatim API.

    Rate limited to 1 request per second. Returns (coords, confidence).
    """
    result = _geocode_via_nominatim_full(place_str)
    if result and result.get("coords"):
        return result["coords"], result["confidence"]
    return None, "low"


def _geocode_via_nominatim_full(
    place_str: str,
) -> dict | None:
    """Geocode using OpenStreetMap Nominatim API with full metadata.

    Rate limited to 1 request per second.
    Returns dict with coords, confidence, bbox, and is_region flag.
    """
    global _last_nominatim_request

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed, Nominatim geocoding disabled")
        return None

    # Rate limiting
    with _nominatim_lock:
        elapsed = time.time() - _last_nominatim_request
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_nominatim_request = time.time()

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": place_str,
            "format": "json",
            "limit": 1,
        }
        headers = {"User-Agent": "GEDCOM-MCP-Server/1.0"}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data:
            result = data[0]
            lat = float(result["lat"])
            lon = float(result["lon"])

            # Extract bounding box [south, north, west, east]
            bbox = result.get("boundingbox")
            bbox_dict = None
            is_region = False
            if bbox and len(bbox) == 4:
                south, north, west, east = map(float, bbox)
                bbox_dict = {"south": south, "north": north, "west": west, "east": east}
                # Determine if this is a region (large bbox) or point (small bbox)
                lat_span = north - south
                lon_span = abs(east - west)
                is_region = lat_span > _REGION_BBOX_THRESHOLD or lon_span > _REGION_BBOX_THRESHOLD

            # Confidence based on result type
            importance = float(result.get("importance", 0.5))
            confidence = "high" if importance > 0.6 else "medium" if importance > 0.3 else "low"

            return {
                "coords": (lat, lon),
                "confidence": confidence,
                "bbox": bbox_dict,
                "is_region": is_region,
                "display_name": result.get("display_name", place_str),
            }
    except Exception as e:
        logger.debug(f"Nominatim geocoding failed for '{place_str}': {e}")

    return None


def _geocode_place_full(
    place: Place,
) -> tuple[tuple[float, float] | None, str, str]:
    """Geocode a place using all available methods.

    Returns (coords, source, confidence).
    """
    global _geocache, _geocache_dirty

    place_id = place.id

    # Check cache first
    if place_id in _geocache:
        cached = _geocache[place_id]
        if cached["lat"] is not None:
            return (cached["lat"], cached["lon"]), cached["source"], cached["confidence"]
        # Already tried and failed
        return None, cached["source"], cached["confidence"]

    # Check if inherently un-geocodable
    if _is_ungeocodable(place.original):
        _geocache[place_id] = {
            "lat": None,
            "lon": None,
            "source": "not_found",
            "confidence": "low",
        }
        _geocache_dirty = True
        return None, "not_found", "low"

    # Tier 1: Check if already geocoded in Place object
    if place.latitude is not None and place.longitude is not None:
        _geocache[place_id] = {
            "lat": place.latitude,
            "lon": place.longitude,
            "source": "gedcom",
            "confidence": "high",
        }
        _geocache_dirty = True
        return (place.latitude, place.longitude), "gedcom", "high"

    # Tier 2: Try geonamescache
    coords, confidence = _geocode_via_geonamescache(place.normalized)
    if coords:
        place.latitude, place.longitude = coords
        _geocache[place_id] = {
            "lat": coords[0],
            "lon": coords[1],
            "source": "geonamescache",
            "confidence": confidence,
        }
        _geocache_dirty = True
        return coords, "geonamescache", confidence

    # Tier 3: Try Nominatim
    coords, confidence = _geocode_via_nominatim(place.original)
    if coords:
        place.latitude, place.longitude = coords
        _geocache[place_id] = {
            "lat": coords[0],
            "lon": coords[1],
            "source": "nominatim",
            "confidence": confidence,
        }
        _geocache_dirty = True
        return coords, "nominatim", confidence

    # Mark as not found
    _geocache[place_id] = {
        "lat": None,
        "lon": None,
        "source": "not_found",
        "confidence": "low",
    }
    _geocache_dirty = True
    logger.info(
        f"Low confidence geocode: '{place.original}' → not found "
        f"(source: not_found, confidence: low, reason: no matches)"
    )
    return None, "not_found", "low"


def _geocode_worker() -> None:
    """Background thread to geocode all places."""
    global _geocoding_progress, _geocache_dirty

    # Count places
    total_places = len(state.places)
    pending = sum(1 for p in state.places.values() if p.latitude is None and p.id not in _geocache)

    with _geocoding_lock:
        _geocoding_progress = {
            "status": "running",
            "total": total_places,
            "geocoded": total_places - pending,
            "pending": pending,
            "percent": int((total_places - pending) / total_places * 100)
            if total_places > 0
            else 0,
        }

    # Geocode each place
    geocoded_count = 0
    for place in state.places.values():
        if place.id in _geocache and _geocache[place.id]["lat"] is not None:
            geocoded_count += 1
            continue
        if place.latitude is not None:
            geocoded_count += 1
            continue

        coords, source, confidence = _geocode_place_full(place)
        if coords:
            geocoded_count += 1

        # Update progress
        with _geocoding_lock:
            _geocoding_progress["geocoded"] = geocoded_count
            _geocoding_progress["pending"] = total_places - geocoded_count
            _geocoding_progress["percent"] = (
                int(geocoded_count / total_places * 100) if total_places > 0 else 0
            )

        # Save cache periodically (every 50 places)
        if _geocache_dirty and geocoded_count % 50 == 0:
            _save_geocache()

    # Final save and update status
    if _geocache_dirty:
        _save_geocache()

    with _geocoding_lock:
        _geocoding_progress["status"] = "complete"
        _geocoding_progress["geocoded"] = geocoded_count
        _geocoding_progress["percent"] = (
            int(geocoded_count / total_places * 100) if total_places > 0 else 100
        )

    logger.info(f"Geocoding complete: {geocoded_count}/{total_places} places geocoded")


def start_geocoding_thread() -> None:
    """Start background geocoding thread. Call after load_gedcom()."""
    global _geocoding_progress

    if not is_enabled():
        with _geocoding_lock:
            _geocoding_progress["status"] = "disabled"
        return

    # Load cache first
    _load_geocache()

    # Start background thread
    thread = threading.Thread(target=_geocode_worker, daemon=True)
    thread.start()
    logger.info("Started background geocoding thread")


def _resolve_location(
    query: str,
) -> tuple[tuple[float, float] | None, str, str, str]:
    """Resolve a location query to coordinates.

    Tries to match against GEDCOM places first, then external geocoding.

    Returns (coords, matched_place, source, confidence).
    """
    query_normalized = normalize_place_string(query)

    # Strategy 1: Exact match in GEDCOM places
    for place in state.places.values():
        if place.normalized == query_normalized:
            if place.latitude is not None and place.longitude is not None:
                return (
                    (place.latitude, place.longitude),
                    place.original,
                    "gedcom",
                    "high",
                )
            # Found place but no coords - geocode it
            coords, source, confidence = _geocode_place_full(place)
            if coords:
                return coords, place.original, source, confidence

    # Strategy 2: Fuzzy match in GEDCOM places
    place_names = {p.id: p.normalized for p in state.places.values()}
    if place_names:
        matches = process.extract(
            query_normalized,
            list(place_names.values()),
            scorer=fuzz.WRatio,
            limit=5,
            score_cutoff=80,
        )

        for match_name, score, _ in matches:
            # Find the place with this normalized name
            for place in state.places.values():
                if place.normalized == match_name:
                    if place.latitude is not None and place.longitude is not None:
                        confidence = "high" if score >= 95 else "medium"
                        return (
                            (place.latitude, place.longitude),
                            place.original,
                            "gedcom",
                            confidence,
                        )
                    # Geocode the matched place
                    coords, source, geo_confidence = _geocode_place_full(place)
                    if coords:
                        # Lower confidence if fuzzy match
                        confidence = geo_confidence if score >= 95 else "medium"
                        return coords, place.original, source, confidence
                    break

    # Strategy 3: Direct geocoding of query
    coords, confidence = _geocode_via_geonamescache(query_normalized)
    if coords:
        return coords, query, "geonamescache", confidence

    coords, confidence = _geocode_via_nominatim(query)
    if coords:
        return coords, query, "nominatim", confidence

    return None, query, "not_found", "low"


def _resolve_location_with_bbox(
    query: str,
) -> dict:
    """Resolve a location query to coordinates and bounding box.

    Used for mode="within" searches. Prioritizes Nominatim for bbox data.

    Returns dict with:
        coords: (lat, lon) tuple or None
        matched: matched place name
        source: "gedcom", "geonamescache", "nominatim", or "not_found"
        confidence: "high", "medium", or "low"
        bbox: {"south", "north", "west", "east"} or None
        is_region: True if bbox indicates a large region (state/country)
    """
    query_normalized = normalize_place_string(query)

    # For bbox queries, prioritize Nominatim since it provides bounding boxes
    nominatim_result = _geocode_via_nominatim_full(query)

    if nominatim_result:
        return {
            "coords": nominatim_result["coords"],
            "matched": nominatim_result["display_name"],
            "source": "nominatim",
            "confidence": nominatim_result["confidence"],
            "bbox": nominatim_result["bbox"],
            "is_region": nominatim_result["is_region"],
        }

    # Fallback: check GEDCOM places (no bbox available)
    for place in state.places.values():
        if place.normalized == query_normalized:
            if place.latitude is not None:
                return {
                    "coords": (place.latitude, place.longitude),
                    "matched": place.original,
                    "source": "gedcom",
                    "confidence": "high",
                    "bbox": None,
                    "is_region": False,
                }
            # Try to geocode via Nominatim to get bbox
            nominatim_result = _geocode_via_nominatim_full(place.original)
            if nominatim_result:
                return {
                    "coords": nominatim_result["coords"],
                    "matched": place.original,
                    "source": "nominatim",
                    "confidence": nominatim_result["confidence"],
                    "bbox": nominatim_result["bbox"],
                    "is_region": nominatim_result["is_region"],
                }

    # Fallback: geonamescache (no bbox)
    coords, confidence = _geocode_via_geonamescache(query_normalized)
    if coords:
        return {
            "coords": coords,
            "matched": query,
            "source": "geonamescache",
            "confidence": confidence,
            "bbox": None,
            "is_region": False,
        }

    return {
        "coords": None,
        "matched": query,
        "source": "not_found",
        "confidence": "low",
        "bbox": None,
        "is_region": False,
    }


def _point_in_bbox(lat: float, lon: float, bbox: dict) -> bool:
    """Check if a point falls within a bounding box."""
    return bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]


def _search_within_bbox(
    bbox: dict,
    event_types: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """Find individuals with events inside a bounding box.

    Args:
        bbox: Dict with south, north, west, east coordinates
        event_types: Optional filter ["BIRT", "DEAT", "MARR", etc.]
        max_results: Maximum results to return

    Returns:
        List of result dicts with individual_id, name, and matching_places.
    """
    results: list[dict] = []
    seen_individuals: set[str] = set()

    for place in state.places.values():
        if place.latitude is None or place.longitude is None:
            continue

        # Check if place is inside the bounding box
        if not _point_in_bbox(place.latitude, place.longitude, bbox):
            continue

        # Find individuals associated with this place
        place_id = place.id
        for indi_id, indi_place_ids in state.individual_places.items():
            if place_id not in indi_place_ids:
                continue

            indi = state.individuals.get(indi_id)
            if not indi:
                continue

            # Collect matching events at this place
            matching_events: list[dict] = []
            for event in indi.events:
                if event.place:
                    event_place_id = get_place_id(event.place)
                    if event_place_id == place_id:
                        if event_types and event.type not in event_types:
                            continue
                        cached = _geocache.get(place_id, {})
                        matching_events.append(
                            {
                                "place": event.place,
                                "event": event.type,
                                "date": event.date,
                                "geocode_confidence": cached.get("confidence", "unknown"),
                                "geocode_source": cached.get("source", "unknown"),
                            }
                        )

            # Check birth/death places
            if indi.birth_place:
                bp_id = get_place_id(indi.birth_place)
                if bp_id == place_id and (not event_types or "BIRT" in event_types):
                    cached = _geocache.get(place_id, {})
                    matching_events.append(
                        {
                            "place": indi.birth_place,
                            "event": "BIRT",
                            "date": indi.birth_date,
                            "geocode_confidence": cached.get("confidence", "unknown"),
                            "geocode_source": cached.get("source", "unknown"),
                        }
                    )

            if indi.death_place:
                dp_id = get_place_id(indi.death_place)
                if dp_id == place_id and (not event_types or "DEAT" in event_types):
                    cached = _geocache.get(place_id, {})
                    matching_events.append(
                        {
                            "place": indi.death_place,
                            "event": "DEAT",
                            "date": indi.death_date,
                            "geocode_confidence": cached.get("confidence", "unknown"),
                            "geocode_source": cached.get("source", "unknown"),
                        }
                    )

            if not matching_events:
                continue

            if indi_id in seen_individuals:
                # Add new matching places to existing result
                for r in results:
                    if r["individual_id"] == indi_id:
                        existing_places = {(e["place"], e["event"]) for e in r["matching_places"]}
                        for me in matching_events:
                            if (me["place"], me["event"]) not in existing_places:
                                r["matching_places"].append(me)
                        break
            else:
                seen_individuals.add(indi_id)
                results.append(
                    {
                        "individual_id": indi_id,
                        "name": indi.full_name(),
                        "matching_places": matching_events,
                    }
                )

                if len(results) >= max_results:
                    return results

    return results


def _search_nearby(
    location: str,
    radius_miles: float = 50,
    event_types: list[str] | None = None,
    unit: Literal["miles", "km"] = "miles",
    max_results: int = 100,
    mode: Literal["proximity", "within"] = "proximity",
) -> dict:
    """Find individuals with events near or within a location.

    Args:
        location: Place name to search around (fuzzy matched)
        radius_miles: Search radius (default 50, max 500) - ignored when mode="within"
        event_types: Optional filter ["BIRT", "DEAT", "MARR", etc.]
        unit: Distance unit - "miles" (default) or "km"
        max_results: Maximum results to return (default 100)
        mode: Search mode:
            - "proximity" (default): Find people within X miles of the location's center point
            - "within": Find people with events inside the location's bounding box

    Returns:
        Dictionary with reference_location, mode, geocoding_status,
        coverage, result_count, and results list.
    """
    if not is_enabled():
        return {
            "error": "GIS search not enabled. Set GIS_SEARCH_ENABLED=true",
            "results": [],
        }

    # Get geocoding status and coverage info (common to both modes)
    geo_status = get_geocoding_status()
    total_places = len(state.places)
    geocoded_count = sum(1 for p in state.places.values() if p.latitude is not None)
    coverage_percent = int(geocoded_count / total_places * 100) if total_places > 0 else 0

    coverage_info = {
        "geocoded": geocoded_count,
        "total": total_places,
        "percent": coverage_percent,
    }
    coverage_note = (
        f"{coverage_percent}% of places geocoded. Results are a lower bound."
        if coverage_percent < 100
        else "All places geocoded."
    )

    # Handle "within" mode (bounding box containment)
    if mode == "within":
        return _search_within_mode(
            location=location,
            event_types=event_types,
            max_results=max_results,
            geo_status=geo_status,
            coverage_info=coverage_info,
            coverage_note=coverage_note,
        )

    # Handle "proximity" mode (default - distance from center point)
    return _search_proximity_mode(
        location=location,
        radius_miles=radius_miles,
        event_types=event_types,
        unit=unit,
        max_results=max_results,
        geo_status=geo_status,
        coverage_info=coverage_info,
        coverage_note=coverage_note,
    )


def _search_within_mode(
    location: str,
    event_types: list[str] | None,
    max_results: int,
    geo_status: dict,
    coverage_info: dict,
    coverage_note: str,
) -> dict:
    """Handle mode='within' - find individuals inside a region's bounding box."""
    # Resolve location with bounding box
    loc_info = _resolve_location_with_bbox(location)

    if loc_info["coords"] is None:
        return {
            "error": f"Could not geocode location: {location}",
            "reference_location": {
                "query": location,
                "matched": None,
                "bounding_box": None,
                "match_confidence": "low",
                "match_source": "not_found",
            },
            "mode": "within",
            "results": [],
        }

    # Check if we have a bounding box
    bbox = loc_info["bbox"]
    if bbox is None:
        # No bbox available - fall back to a small radius around the point
        # This handles cases like geonamescache results
        return {
            "error": (
                f"No bounding box available for '{location}'. "
                "Use mode='proximity' with a specific radius instead."
            ),
            "reference_location": {
                "query": location,
                "matched": loc_info["matched"],
                "coordinates": {"lat": loc_info["coords"][0], "lon": loc_info["coords"][1]},
                "bounding_box": None,
                "match_confidence": loc_info["confidence"],
                "match_source": loc_info["source"],
            },
            "mode": "within",
            "results": [],
        }

    # Search within the bounding box
    results = _search_within_bbox(bbox, event_types, max_results)

    return {
        "reference_location": {
            "query": location,
            "matched": loc_info["matched"],
            "bounding_box": bbox,
            "match_confidence": loc_info["confidence"],
            "match_source": loc_info["source"],
        },
        "mode": "within",
        "geocoding_status": geo_status["status"],
        "coverage": coverage_info,
        "coverage_note": coverage_note,
        "result_count": len(results),
        "results": results,
    }


def _search_proximity_mode(
    location: str,
    radius_miles: float,
    event_types: list[str] | None,
    unit: Literal["miles", "km"],
    max_results: int,
    geo_status: dict,
    coverage_info: dict,
    coverage_note: str,
) -> dict:
    """Handle mode='proximity' - find individuals within X miles of a point."""
    # Clamp radius
    radius_miles = min(max(1, radius_miles), 500)
    radius_display = radius_miles

    # Resolve reference location
    ref_coords, matched_place, match_source, match_confidence = _resolve_location(location)

    if ref_coords is None:
        return {
            "error": f"Could not geocode location: {location}",
            "reference_location": {
                "query": location,
                "matched": None,
                "coordinates": None,
                "match_confidence": "low",
                "match_source": "not_found",
            },
            "mode": "proximity",
            "results": [],
        }

    # Check if this is a large region and warn
    region_warning = None
    nominatim_info = _geocode_via_nominatim_full(location)
    if nominatim_info and nominatim_info.get("is_region"):
        region_warning = (
            f"'{location}' appears to be a large region (state/country). "
            "Consider using mode='within' to search by region boundary instead."
        )

    # Search for individuals near the reference point
    results: list[dict] = []
    seen_individuals: set[str] = set()

    for place in state.places.values():
        if place.latitude is None or place.longitude is None:
            continue

        # Calculate distance
        dist = haversine(
            ref_coords,
            (place.latitude, place.longitude),
            unit=Unit.KILOMETERS if unit == "km" else Unit.MILES,
        )

        if dist > radius_display:
            continue

        # Find individuals associated with this place
        place_id = place.id
        for indi_id, indi_place_ids in state.individual_places.items():
            if place_id not in indi_place_ids:
                continue

            indi = state.individuals.get(indi_id)
            if not indi:
                continue

            # Collect matching events at this place
            matching_events: list[dict] = []
            for event in indi.events:
                if event.place:
                    event_place_id = get_place_id(event.place)
                    if event_place_id == place_id:
                        # Filter by event type if specified
                        if event_types and event.type not in event_types:
                            continue
                        # Get geocode info for this place
                        cached = _geocache.get(place_id, {})
                        matching_events.append(
                            {
                                "place": event.place,
                                "event": event.type,
                                "date": event.date,
                                "geocode_confidence": cached.get("confidence", "unknown"),
                                "geocode_source": cached.get("source", "unknown"),
                            }
                        )

            # Also check birth/death places
            if indi.birth_place:
                bp_id = get_place_id(indi.birth_place)
                if bp_id == place_id and (not event_types or "BIRT" in event_types):
                    cached = _geocache.get(place_id, {})
                    matching_events.append(
                        {
                            "place": indi.birth_place,
                            "event": "BIRT",
                            "date": indi.birth_date,
                            "geocode_confidence": cached.get("confidence", "unknown"),
                            "geocode_source": cached.get("source", "unknown"),
                        }
                    )

            if indi.death_place:
                dp_id = get_place_id(indi.death_place)
                if dp_id == place_id and (not event_types or "DEAT" in event_types):
                    cached = _geocache.get(place_id, {})
                    matching_events.append(
                        {
                            "place": indi.death_place,
                            "event": "DEAT",
                            "date": indi.death_date,
                            "geocode_confidence": cached.get("confidence", "unknown"),
                            "geocode_source": cached.get("source", "unknown"),
                        }
                    )

            if not matching_events:
                continue

            if indi_id in seen_individuals:
                # Add new matching places to existing result
                for r in results:
                    if r["individual_id"] == indi_id:
                        # Update distance if closer
                        if dist < r["distance_miles"]:
                            r["distance_miles"] = round(dist, 1)
                        # Add new matching events
                        existing_places = {(e["place"], e["event"]) for e in r["matching_places"]}
                        for me in matching_events:
                            if (me["place"], me["event"]) not in existing_places:
                                r["matching_places"].append(me)
                        break
            else:
                seen_individuals.add(indi_id)
                results.append(
                    {
                        "individual_id": indi_id,
                        "name": indi.full_name(),
                        "distance_miles": round(dist, 1),
                        "matching_places": matching_events,
                    }
                )

    # Sort by distance
    results.sort(key=lambda x: x["distance_miles"])
    results = results[:max_results]

    # Build response
    response = {
        "reference_location": {
            "query": location,
            "matched": matched_place,
            "coordinates": {"lat": ref_coords[0], "lon": ref_coords[1]},
            "match_confidence": match_confidence,
            "match_source": match_source,
        },
        "mode": "proximity",
        "search_radius_miles": radius_display,
        "unit": unit,
        "geocoding_status": geo_status["status"],
        "coverage": coverage_info,
        "coverage_note": coverage_note,
        "result_count": len(results),
        "results": results,
    }

    if region_warning:
        response["region_warning"] = region_warning

    return response
