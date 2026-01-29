"""Fuzzy place search and geocoding functions."""

import jellyfish
from haversine import Unit, haversine
from rapidfuzz import fuzz, process

from . import state
from .constants import HISTORICAL_MAPPINGS
from .helpers import (
    geocode_place_coords,
    get_place_id,
    normalize_place_string,
    parse_place_components,
)


def _get_historical_variants(place: str) -> list[str]:
    """Get historical name variants for a place."""
    place_lower = place.lower()
    variants = []

    # Check each word in the place string
    words = place_lower.split()
    for word in words:
        if word in HISTORICAL_MAPPINGS:
            variants.extend(HISTORICAL_MAPPINGS[word])

    # Also check full place components
    components = parse_place_components(place)
    for comp in components:
        comp_lower = comp.lower()
        if comp_lower in HISTORICAL_MAPPINGS:
            variants.extend(HISTORICAL_MAPPINGS[comp_lower])

    return list(set(variants))


def _fuzzy_match_places(query: str, threshold: int = 70) -> list[tuple[str, float]]:
    """Find places matching query with fuzzy string matching.

    Returns list of (original_place, score) tuples sorted by score descending.
    """
    query_norm = normalize_place_string(query)

    # Get unique place strings from the places index
    unique_places = [p.original for p in state.places.values()]

    if not unique_places:
        return []

    # Also normalize the choices for better matching
    choices_normalized = {p.original: p.normalized for p in state.places.values()}

    # Use rapidfuzz to find matches
    matches = process.extract(
        query_norm,
        [choices_normalized[p] for p in unique_places],
        scorer=fuzz.WRatio,
        limit=100,
        score_cutoff=threshold,
    )

    # Map back to original place strings
    result = []
    for match in matches:
        # Find the original string for this normalized match
        normalized_match = match[0]
        score = match[1]
        for orig, norm in choices_normalized.items():
            if norm == normalized_match:
                result.append((orig, score))
                break

    return result


def _phonetic_match_places(query: str) -> list[str]:
    """Find places with similar pronunciation using Metaphone.

    Returns list of original place strings that match phonetically.
    """
    # Get metaphone code for query (first significant word)
    query_words = query.split(",")[0].strip().split()
    if not query_words:
        return []

    query_code = jellyfish.metaphone(query_words[0])
    matches = []

    for place in state.places.values():
        # Check first word of place (usually city name)
        place_words = place.original.split(",")[0].strip().split()
        if place_words:
            place_code = jellyfish.metaphone(place_words[0])
            if place_code == query_code:
                matches.append(place.original)

    return matches


def _fuzzy_search_place(place: str, threshold: int = 70, max_results: int = 50) -> list[dict]:
    """Search for individuals by place with fuzzy matching.

    Uses a multi-strategy approach:
    1. Exact substring match
    2. Normalized match (abbreviation expansion)
    3. Fuzzy string matching (typo tolerance)
    4. Phonetic matching (pronunciation similarity)
    5. Historical name variants
    """
    results = []
    seen_individuals: set[str] = set()
    place_scores: dict[str, float] = {}  # place -> best score

    # Strategy 1: Exact substring match (highest score)
    place_lower = place.lower()
    for indexed_place in state.place_index:
        if place_lower in indexed_place:
            place_scores[indexed_place] = 100.0

    # Strategy 2: Normalized match
    place_normalized = normalize_place_string(place)
    for p in state.places.values():
        if place_normalized in p.normalized and p.original.lower() not in place_scores:
            place_scores[p.original.lower()] = 95.0

    # Strategy 3: Fuzzy string match
    fuzzy_matches = _fuzzy_match_places(place, threshold)
    for orig_place, score in fuzzy_matches:
        key = orig_place.lower()
        if key not in place_scores or place_scores[key] < score:
            place_scores[key] = score

    # Strategy 4: Phonetic match
    phonetic_matches = _phonetic_match_places(place)
    for orig_place in phonetic_matches:
        key = orig_place.lower()
        if key not in place_scores:
            place_scores[key] = 60.0  # Base score for phonetic match

    # Strategy 5: Historical variants
    variants = _get_historical_variants(place)
    for variant in variants:
        variant_lower = variant.lower()
        for indexed_place in state.place_index:
            if variant_lower in indexed_place and indexed_place not in place_scores:
                place_scores[indexed_place] = 80.0  # Historical match score

    # Collect individuals from matching places
    for matching_place, score in sorted(place_scores.items(), key=lambda x: -x[1]):
        if matching_place in state.place_index:
            for indi_id in state.place_index[matching_place]:
                if indi_id not in seen_individuals and indi_id in state.individuals:
                    seen_individuals.add(indi_id)
                    indi = state.individuals[indi_id]
                    info = indi.to_summary()
                    info["birth_place"] = indi.birth_place
                    info["death_place"] = indi.death_place
                    info["match_score"] = score
                    info["matched_place"] = matching_place
                    results.append(info)
                    if len(results) >= max_results:
                        return results

    return results


def _search_similar_places(place: str, max_results: int = 20) -> list[dict]:
    """Find places in the tree similar to the given name.

    Useful for discovering spelling variations or related locations.
    """
    results = []

    # Get fuzzy matches
    fuzzy_matches = _fuzzy_match_places(place, threshold=50)

    # Get phonetic matches
    phonetic_matches = _phonetic_match_places(place)
    phonetic_set = set(phonetic_matches)

    # Combine results
    seen = set()
    for orig_place, score in fuzzy_matches:
        if orig_place not in seen:
            seen.add(orig_place)
            is_phonetic = orig_place in phonetic_set
            results.append(
                {
                    "place": orig_place,
                    "similarity_score": score,
                    "phonetic_match": is_phonetic,
                }
            )
            if len(results) >= max_results:
                break

    # Add phonetic-only matches not in fuzzy results
    for orig_place in phonetic_matches:
        if orig_place not in seen and len(results) < max_results:
            seen.add(orig_place)
            results.append(
                {
                    "place": orig_place,
                    "similarity_score": 60.0,  # Base phonetic score
                    "phonetic_match": True,
                }
            )

    # Sort by score (descending)
    def get_score(x: dict) -> float:
        return float(x.get("similarity_score", 0))

    results.sort(key=get_score, reverse=True)
    return results[:max_results]


def _get_place_variants(place: str) -> list[dict]:
    """Get all variant spellings/forms of a place found in the tree.

    Groups places that normalize to the same form or match phonetically.
    """
    target_normalized = normalize_place_string(place)
    target_phonetic = (
        jellyfish.metaphone(place.split(",")[0].strip().split()[0])
        if place.split(",")[0].strip()
        else ""
    )

    variants = []
    seen = set()

    for p in state.places.values():
        # Check if normalizes to same form
        if p.normalized == target_normalized:
            if p.original not in seen:
                seen.add(p.original)
                variants.append(
                    {
                        "place": p.original,
                        "match_type": "normalized",
                    }
                )
            continue

        # Check phonetic match
        if target_phonetic:
            place_words = p.original.split(",")[0].strip().split()
            if place_words:
                place_phonetic = jellyfish.metaphone(place_words[0])
                if place_phonetic == target_phonetic and p.original not in seen:
                    seen.add(p.original)
                    variants.append(
                        {
                            "place": p.original,
                            "match_type": "phonetic",
                        }
                    )

    # Also check for fuzzy matches with high threshold
    fuzzy_matches = _fuzzy_match_places(place, threshold=85)
    for orig_place, match_score in fuzzy_matches:
        if orig_place not in seen:
            seen.add(orig_place)
            fuzzy_result: dict = {
                "place": orig_place,
                "match_type": "fuzzy",
                "similarity_score": match_score,
            }
            variants.append(fuzzy_result)

    return variants


def _get_all_places(max_results: int = 500) -> list[dict]:
    """Get all unique places in the tree."""
    results = []
    for place in state.places.values():
        results.append(place.to_summary())
        if len(results) >= max_results:
            break
    return results


def _get_place(place_id: str) -> dict | None:
    """Get a place by its ID."""
    place = state.places.get(place_id)
    if place:
        return place.to_dict()
    return None


def _geocode_place(place: str) -> dict | None:
    """Get coordinates for a place name.

    Returns dict with latitude, longitude, and source of geocoding.
    """
    # First check if we already have this place geocoded
    place_id = get_place_id(place)
    if place_id in state.places:
        p = state.places[place_id]
        if p.latitude is not None:
            return {
                "place": place,
                "latitude": p.latitude,
                "longitude": p.longitude,
                "source": "cached",
            }

    # Try to geocode
    coords = geocode_place_coords(place)
    if coords:
        # Update the place if it exists
        if place_id in state.places:
            state.places[place_id].latitude = coords[0]
            state.places[place_id].longitude = coords[1]
        return {
            "place": place,
            "latitude": coords[0],
            "longitude": coords[1],
            "source": "geonamescache",
        }

    return None


def _search_nearby(
    place: str,
    radius_km: float = 50,
    event_types: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """Find individuals with events within a radius of a place.

    Args:
        place: Reference place name (will be geocoded)
        radius_km: Search radius in kilometers (default 50)
        event_types: Filter by event types (BIRT, DEAT, RESI, etc.)
        max_results: Maximum results to return

    Returns:
        List of individuals with distance info, sorted by distance

    Note: Only places that have been geocoded will be searched.
    Call geocode_place() on specific places to add coordinates.
    """
    # Geocode reference point
    ref_coords = geocode_place_coords(place)
    if not ref_coords:
        # Try to find the place in our index
        place_id = get_place_id(place)
        if place_id in state.places:
            p = state.places[place_id]
            if p.latitude is not None and p.longitude is not None:
                ref_coords = (p.latitude, p.longitude)

    if not ref_coords:
        return []

    results = []
    seen_individuals: set[str] = set()

    for place_id, p in state.places.items():
        if p.latitude is None or p.longitude is None:
            continue

        dist = haversine(ref_coords, (p.latitude, p.longitude), unit=Unit.KILOMETERS)
        if dist <= radius_km:
            # Find individuals at this place
            for indi_id, indi_place_ids in state.individual_places.items():
                if place_id not in indi_place_ids:
                    continue
                if indi_id in seen_individuals:
                    continue
                indi = state.individuals.get(indi_id)
                if not indi:
                    continue

                # Check event types if specified
                if event_types:
                    has_matching_event = False
                    for event in indi.events:
                        if event.type in event_types and event.place:
                            event_place_id = get_place_id(event.place)
                            if event_place_id == place_id:
                                has_matching_event = True
                                break
                    if not has_matching_event:
                        continue

                seen_individuals.add(indi_id)
                info = indi.to_summary()
                info["place"] = p.original
                info["distance_km"] = round(dist, 1)
                results.append(info)

    # Sort by distance, limit results
    results.sort(key=lambda x: x["distance_km"])
    return results[:max_results]
