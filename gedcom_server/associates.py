"""Associates discovery using the FAN Club (Friends, Associates, Neighbors) technique.

Finds likely neighbors and associates based on time+place overlap - a fundamental
genealogical research technique for discovering collateral lines and community connections.
"""

import time

from rapidfuzz import fuzz

from . import state
from .core import _build_ancestor_set, _normalize_lookup_id
from .helpers import extract_year, normalize_place_string


def _get_lifespan(individual_id: str) -> tuple[int | None, int | None]:
    """Get birth and death years for an individual.

    Returns:
        (birth_year, death_year) tuple, either may be None
    """
    indi = state.individuals.get(individual_id)
    if not indi:
        return (None, None)

    birth_year = extract_year(indi.birth_date)
    death_year = extract_year(indi.death_date)
    return (birth_year, death_year)


def _calculate_lifespan_overlap(
    birth1: int | None,
    death1: int | None,
    birth2: int | None,
    death2: int | None,
) -> int | None:
    """Calculate years of overlapping lifespan between two individuals.

    Uses estimated lifespans when death dates are missing (assumes 80 year lifespan).

    Returns:
        Number of overlapping years, or None if cannot be calculated
    """
    if birth1 is None and death1 is None:
        return None
    if birth2 is None and death2 is None:
        return None

    # Estimate death years if missing (assume 80 year lifespan)
    estimated_death1 = death1 if death1 else (birth1 + 80 if birth1 else None)
    estimated_death2 = death2 if death2 else (birth2 + 80 if birth2 else None)

    # Estimate birth years if missing (assume 80 years before death)
    estimated_birth1 = birth1 if birth1 else (death1 - 80 if death1 else None)
    estimated_birth2 = birth2 if birth2 else (death2 - 80 if death2 else None)

    if estimated_birth1 is None or estimated_death1 is None:
        return None
    if estimated_birth2 is None or estimated_death2 is None:
        return None

    # Calculate overlap
    overlap_start = max(estimated_birth1, estimated_birth2)
    overlap_end = min(estimated_death1, estimated_death2)

    if overlap_end > overlap_start:
        return overlap_end - overlap_start
    return 0


def _get_events_with_places(individual_id: str) -> list[dict]:
    """Get all events for an individual that have both date and place.

    Returns:
        List of dicts with {type, year, place, place_normalized}
    """
    indi = state.individuals.get(individual_id)
    if not indi:
        return []

    events = []

    # Add birth/death from individual record
    if indi.birth_place:
        year = extract_year(indi.birth_date)
        events.append(
            {
                "type": "BIRT",
                "year": year,
                "place": indi.birth_place,
                "place_normalized": normalize_place_string(indi.birth_place),
            }
        )

    if indi.death_place:
        year = extract_year(indi.death_date)
        events.append(
            {
                "type": "DEAT",
                "year": year,
                "place": indi.death_place,
                "place_normalized": normalize_place_string(indi.death_place),
            }
        )

    # Add events from events list
    for event in indi.events:
        if event.place:
            year = extract_year(event.date)
            events.append(
                {
                    "type": event.type,
                    "year": year,
                    "place": event.place,
                    "place_normalized": normalize_place_string(event.place),
                }
            )

    return events


def _places_match(place1_normalized: str, place2_normalized: str, threshold: int = 80) -> bool:
    """Check if two normalized places match using fuzzy matching.

    Args:
        place1_normalized: First normalized place string
        place2_normalized: Second normalized place string
        threshold: Minimum fuzzy ratio for match (default 80)

    Returns:
        True if places are considered a match
    """
    # Exact match
    if place1_normalized == place2_normalized:
        return True

    # Fuzzy match
    ratio = fuzz.ratio(place1_normalized, place2_normalized)
    if ratio >= threshold:
        return True

    # Check if one contains the other (for partial matches like "Pittsburgh" vs "Pittsburgh, PA")
    return place1_normalized in place2_normalized or place2_normalized in place1_normalized


def _build_relative_set(individual_id: str, max_generations: int = 5) -> set[str]:
    """Build a set of all known relatives (blood and marriage).

    Includes:
    - Ancestors (via _build_ancestor_set)
    - Descendants
    - Spouses of self and all ancestors/descendants
    - Siblings and their families

    Args:
        individual_id: The GEDCOM ID
        max_generations: Max generations to traverse

    Returns:
        Set of relative GEDCOM IDs
    """
    relatives: set[str] = {individual_id}
    indi = state.individuals.get(individual_id)
    if not indi:
        return relatives

    # Add ancestors
    ancestor_dict = _build_ancestor_set(individual_id, max_generations)
    relatives.update(ancestor_dict.keys())

    # Add spouses of self
    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            if fam.husband_id:
                relatives.add(fam.husband_id)
            if fam.wife_id:
                relatives.add(fam.wife_id)
            # Add children
            relatives.update(fam.children_ids)

    # Add siblings
    if indi.family_as_child:
        fam = state.families.get(indi.family_as_child)
        if fam:
            for child_id in fam.children_ids:
                relatives.add(child_id)

    # For each ancestor, add their spouses
    for ancestor_id in list(relatives):
        ancestor = state.individuals.get(ancestor_id)
        if ancestor:
            for fam_id in ancestor.families_as_spouse:
                fam = state.families.get(fam_id)
                if fam:
                    if fam.husband_id:
                        relatives.add(fam.husband_id)
                    if fam.wife_id:
                        relatives.add(fam.wife_id)

    # Traverse descendants (limited depth)
    def add_descendants(indi_id: str, depth: int) -> None:
        if depth <= 0:
            return
        desc = state.individuals.get(indi_id)
        if not desc:
            return
        for fam_id in desc.families_as_spouse:
            fam = state.families.get(fam_id)
            if fam:
                # Add spouse
                spouse_id = fam.wife_id if fam.husband_id == indi_id else fam.husband_id
                if spouse_id:
                    relatives.add(spouse_id)
                # Add and recurse into children
                for child_id in fam.children_ids:
                    relatives.add(child_id)
                    add_descendants(child_id, depth - 1)

    add_descendants(individual_id, max_generations)

    return relatives


def _get_candidate_ids_by_place(
    target_places: set[str], place_filter: str | None = None
) -> set[str]:
    """Get candidate individual IDs from place index.

    Uses the place_index for O(1) lookup of individuals at matching places.

    Args:
        target_places: Set of normalized place strings to match
        place_filter: Optional place filter to further restrict

    Returns:
        Set of individual IDs at matching places
    """
    candidates: set[str] = set()
    place_filter_normalized = normalize_place_string(place_filter) if place_filter else None

    for indexed_place, indi_ids in state.place_index.items():
        # Check if this indexed place matches any target place
        for target_place in target_places:
            if _places_match(target_place, indexed_place, threshold=75):
                # If place filter specified, also check against it
                if place_filter_normalized and not _places_match(
                    place_filter_normalized, indexed_place, threshold=70
                ):
                    continue
                candidates.update(indi_ids)
                break

    return candidates


def _calculate_association_strength(
    target_events: list[dict],
    candidate_events: list[dict],
    target_birth: int | None,
    target_death: int | None,
    candidate_birth: int | None,
    candidate_death: int | None,
) -> tuple[float, list[dict], int | None]:
    """Calculate association strength between two individuals.

    Scoring:
    - Same place + same year: +0.15
    - Same place + within 5 years: +0.08
    - Lifespan overlap: up to +0.30 (normalized by max possible overlap)
    - Multiple distinct places: +0.05 each additional place

    Returns:
        (strength, overlapping_events, lifespan_overlap_years)
    """
    strength = 0.0
    overlapping_events: list[dict] = []
    matched_places: set[str] = set()

    # Compare events
    for t_event in target_events:
        t_place = t_event["place_normalized"]
        t_year = t_event["year"]

        for c_event in candidate_events:
            c_place = c_event["place_normalized"]
            c_year = c_event["year"]

            if _places_match(t_place, c_place, threshold=75):
                # Record the overlap
                overlap_info = {
                    "target_event": t_event["type"],
                    "target_year": t_year,
                    "target_place": t_event["place"],
                    "candidate_event": c_event["type"],
                    "candidate_year": c_year,
                    "candidate_place": c_event["place"],
                }

                if t_year is not None and c_year is not None:
                    year_diff = abs(t_year - c_year)
                    if year_diff == 0:
                        strength += 0.15
                        overlap_info["overlap_type"] = "same_year"
                    elif year_diff <= 5:
                        strength += 0.08
                        overlap_info["overlap_type"] = "within_5_years"
                    else:
                        strength += 0.02  # Same place, different time
                        overlap_info["overlap_type"] = "same_place"
                else:
                    strength += 0.03  # Same place, unknown timing
                    overlap_info["overlap_type"] = "same_place_unknown_year"

                overlapping_events.append(overlap_info)
                matched_places.add(t_place)

    # Bonus for multiple distinct places
    if len(matched_places) > 1:
        strength += 0.05 * (len(matched_places) - 1)

    # Lifespan overlap bonus
    lifespan_overlap = _calculate_lifespan_overlap(
        target_birth, target_death, candidate_birth, candidate_death
    )
    if lifespan_overlap is not None and lifespan_overlap > 0:
        # Normalize: max 30% boost for 50+ years overlap
        overlap_score = min(lifespan_overlap / 50.0, 1.0) * 0.30
        strength += overlap_score

    # Cap at 1.0
    strength = min(strength, 1.0)

    return (strength, overlapping_events, lifespan_overlap)


def _find_associates(
    individual_id: str,
    place: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    exclude_relatives: bool = True,
    max_results: int = 50,
) -> dict:
    """Find likely neighbors and associates based on time+place overlap.

    Implements the genealogist's FAN Club technique (Friends, Associates, Neighbors)
    by finding people who overlap in time AND place but are NOT known relatives.

    Args:
        individual_id: GEDCOM ID of the focal individual
        place: Optional - filter to specific location
        start_year: Optional - filter time range start
        end_year: Optional - filter time range end
        exclude_relatives: Filter out blood/marriage relatives (default True)
        max_results: Limit results (default 50, max 200)

    Returns:
        Dict with individual info, filters applied, associates list with strength scores
    """
    start_time = time.time()
    max_results = min(max_results, 200)

    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)

    # Build result structure
    result: dict = {
        "individual": None,
        "filters_applied": {
            "place": place,
            "date_range": (f"{start_year}-{end_year}" if start_year or end_year else None),
            "exclude_relatives": exclude_relatives,
        },
        "result_count": 0,
        "associates": [],
        "computation_stats": {
            "candidates_scanned": 0,
            "relatives_filtered": 0,
            "time_ms": 0,
        },
    }

    if not indi:
        result["error"] = "Individual not found"
        return result

    # Get target individual info
    target_birth, target_death = _get_lifespan(lookup_id)
    lifespan_str = None
    if target_birth or target_death:
        lifespan_str = f"{target_birth or '?'}-{target_death or '?'}"

    result["individual"] = {
        "id": lookup_id,
        "name": indi.full_name(),
        "birth_date": indi.birth_date,
        "death_date": indi.death_date,
        "lifespan": lifespan_str,
    }

    # Get target's events with places
    target_events = _get_events_with_places(lookup_id)

    # Apply date filter to target events
    if start_year or end_year:
        filtered_events = []
        for event in target_events:
            event_year = event["year"]
            if event_year is None:
                filtered_events.append(event)  # Keep events without years
            elif (start_year and event_year < start_year) or (end_year and event_year > end_year):
                continue
            else:
                filtered_events.append(event)
        target_events = filtered_events

    if not target_events:
        result["error"] = "No events with places found for this individual"
        return result

    # Collect normalized places from target events
    target_places = {e["place_normalized"] for e in target_events}

    # Apply place filter
    if place:
        place_normalized = normalize_place_string(place)
        target_places = {p for p in target_places if _places_match(p, place_normalized)}
        if not target_places:
            result["error"] = f"No events found matching place filter: {place}"
            return result

    # Get candidates from place index
    candidate_ids = _get_candidate_ids_by_place(target_places, place)
    candidate_ids.discard(lookup_id)  # Remove self

    # Build relative set if needed
    relatives: set[str] = set()
    if exclude_relatives:
        relatives = _build_relative_set(lookup_id)

    # Score candidates
    associates: list[dict] = []
    candidates_scanned = 0
    relatives_filtered = 0

    for cand_id in candidate_ids:
        candidates_scanned += 1

        is_relative = cand_id in relatives
        if exclude_relatives and is_relative:
            relatives_filtered += 1
            continue

        cand = state.individuals.get(cand_id)
        if not cand:
            continue

        # Get candidate's events
        cand_events = _get_events_with_places(cand_id)

        # Apply date filter to candidate events
        if start_year or end_year:
            filtered_cand_events = []
            for event in cand_events:
                event_year = event["year"]
                if event_year is None:
                    filtered_cand_events.append(event)
                elif (start_year and event_year < start_year) or (
                    end_year and event_year > end_year
                ):
                    continue
                else:
                    filtered_cand_events.append(event)
            cand_events = filtered_cand_events

        if not cand_events:
            continue

        # Calculate association strength
        cand_birth, cand_death = _get_lifespan(cand_id)
        strength, overlapping_events, lifespan_overlap = _calculate_association_strength(
            target_events,
            cand_events,
            target_birth,
            target_death,
            cand_birth,
            cand_death,
        )

        if strength > 0 and overlapping_events:
            associates.append(
                {
                    "id": cand_id,
                    "name": cand.full_name(),
                    "birth_date": cand.birth_date,
                    "death_date": cand.death_date,
                    "association_strength": round(strength, 3),
                    "overlapping_events": overlapping_events[:5],  # Limit to top 5 overlaps
                    "lifespan_overlap_years": lifespan_overlap,
                    "is_relative": is_relative,
                }
            )

    # Sort by strength descending
    associates.sort(key=lambda x: -x["association_strength"])

    # Apply max_results
    associates = associates[:max_results]

    elapsed_ms = int((time.time() - start_time) * 1000)

    result["result_count"] = len(associates)
    result["associates"] = associates
    result["computation_stats"] = {
        "candidates_scanned": candidates_scanned,
        "relatives_filtered": relatives_filtered,
        "time_ms": elapsed_ms,
    }

    return result
