"""Core logic functions for querying genealogy data."""

from . import state


def _normalize_lookup_id(id_str: str) -> str:
    """Normalize an ID for lookup in the dictionaries.

    IDs are stored with @ symbols (e.g., '@I123@'), so we ensure
    the lookup ID has them.
    """
    stripped = id_str.strip("@")
    return f"@{stripped}@"


def _search_individuals(name: str, max_results: int = 50) -> list[dict]:
    name_lower = name.lower()
    results = []

    for indi in state.individuals.values():
        if (
            name_lower in indi.given_name.lower()
            or name_lower in indi.surname.lower()
            or name_lower in indi.full_name().lower()
        ):
            results.append(indi.to_summary())
            if len(results) >= max_results:
                break

    return results


def _get_individual(individual_id: str) -> dict | None:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    return indi.to_dict() if indi else None


def _get_family(family_id: str) -> dict | None:
    lookup_id = _normalize_lookup_id(family_id)
    fam = state.families.get(lookup_id)
    if not fam:
        return None

    result = fam.to_dict()

    # Add names for convenience
    if fam.husband_id and fam.husband_id in state.individuals:
        result["husband_name"] = state.individuals[fam.husband_id].full_name()
    if fam.wife_id and fam.wife_id in state.individuals:
        result["wife_name"] = state.individuals[fam.wife_id].full_name()

    result["children"] = []
    for child_id in fam.children_ids:
        if child_id in state.individuals:
            result["children"].append(state.individuals[child_id].to_summary())

    return result


def _get_parents(individual_id: str) -> dict | None:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi or not indi.family_as_child:
        return None

    fam = state.families.get(indi.family_as_child)
    if not fam:
        return None

    result = {"family_id": fam.id, "father": None, "mother": None}

    if fam.husband_id and fam.husband_id in state.individuals:
        result["father"] = state.individuals[fam.husband_id].to_dict()  # type: ignore[assignment]
    if fam.wife_id and fam.wife_id in state.individuals:
        result["mother"] = state.individuals[fam.wife_id].to_dict()  # type: ignore[assignment]

    return result


def _get_children(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    children = []
    seen = set()

    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            for child_id in fam.children_ids:
                if child_id not in seen and child_id in state.individuals:
                    seen.add(child_id)
                    children.append(state.individuals[child_id].to_summary())

    return children


def _get_spouses(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return []

    spouses = []

    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            spouse_id = fam.wife_id if fam.husband_id == lookup_id else fam.husband_id
            if spouse_id and spouse_id in state.individuals:
                spouse_info = state.individuals[spouse_id].to_summary()
                spouse_info["family_id"] = fam_id
                spouse_info["marriage_date"] = fam.marriage_date
                spouse_info["marriage_place"] = fam.marriage_place
                spouses.append(spouse_info)

    return spouses


def _get_siblings(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi or not indi.family_as_child:
        return []

    fam = state.families.get(indi.family_as_child)
    if not fam:
        return []

    siblings = []
    for child_id in fam.children_ids:
        if child_id != lookup_id and child_id in state.individuals:
            siblings.append(state.individuals[child_id].to_summary())

    return siblings


def _get_ancestors(individual_id: str, generations: int = 4) -> dict:
    lookup_id = _normalize_lookup_id(individual_id)
    generations = min(generations, 10)  # Cap at 10 to prevent huge responses

    def build_ancestor_tree(indi_id: str | None, gen: int) -> dict | None:
        if not indi_id or gen <= 0 or indi_id not in state.individuals:
            return None

        indi = state.individuals[indi_id]
        result = indi.to_summary()

        if gen > 1 and indi.family_as_child:
            fam = state.families.get(indi.family_as_child)
            if fam:
                result["father"] = build_ancestor_tree(fam.husband_id, gen - 1)
                result["mother"] = build_ancestor_tree(fam.wife_id, gen - 1)

        return result

    return build_ancestor_tree(lookup_id, generations + 1) or {}


def _get_descendants(individual_id: str, generations: int = 4) -> dict:
    lookup_id = _normalize_lookup_id(individual_id)
    generations = min(generations, 10)

    def build_descendant_tree(indi_id: str | None, gen: int) -> dict | None:
        if not indi_id or gen <= 0 or indi_id not in state.individuals:
            return None

        indi = state.individuals[indi_id]
        result = indi.to_summary()

        if gen > 1:
            children_list = []
            for fam_id in indi.families_as_spouse:
                fam = state.families.get(fam_id)
                if fam:
                    for child_id in fam.children_ids:
                        child_tree = build_descendant_tree(child_id, gen - 1)
                        if child_tree:
                            children_list.append(child_tree)
            if children_list:
                result["children"] = children_list

        return result

    return build_descendant_tree(lookup_id, generations + 1) or {}


def _search_by_birth(
    year: int | None = None,
    place: str | None = None,
    year_range: int = 5,
    max_results: int = 50,
) -> list[dict]:
    results = []
    candidates = set()

    if year:
        for y in range(year - year_range, year + year_range + 1):
            candidates.update(state.birth_year_index.get(y, []))
    else:
        candidates = set(state.individuals.keys())

    place_lower = place.lower() if place else None

    for indi_id in candidates:
        indi = state.individuals.get(indi_id)
        if not indi:
            continue

        if place_lower and (not indi.birth_place or place_lower not in indi.birth_place.lower()):
            continue

        results.append(indi.to_summary())
        if len(results) >= max_results:
            break

    return results


def _search_by_place(place: str, max_results: int = 50) -> list[dict]:
    place_lower = place.lower()
    results = []
    seen = set()

    # Search through place index
    for indexed_place, indi_ids in state.place_index.items():
        if place_lower in indexed_place:
            for indi_id in indi_ids:
                if indi_id not in seen and indi_id in state.individuals:
                    seen.add(indi_id)
                    indi = state.individuals[indi_id]
                    info = indi.to_summary()
                    # Add which places matched
                    info["birth_place"] = indi.birth_place
                    info["death_place"] = indi.death_place
                    results.append(info)
                    if len(results) >= max_results:
                        return results

    return results


def _get_statistics() -> dict:
    # Calculate date ranges
    birth_years = list(state.birth_year_index.keys())
    min_year = min(birth_years) if birth_years else None
    max_year = max(birth_years) if birth_years else None

    # Count by sex
    males = sum(1 for i in state.individuals.values() if i.sex == "M")
    females = sum(1 for i in state.individuals.values() if i.sex == "F")
    unknown_sex = len(state.individuals) - males - females

    # Top surnames
    surname_counts = [(surname, len(ids)) for surname, ids in state.surname_index.items()]
    surname_counts.sort(key=lambda x: -x[1])
    top_surnames = surname_counts[:20]

    return {
        "total_individuals": len(state.individuals),
        "total_families": len(state.families),
        "males": males,
        "females": females,
        "unknown_sex": unknown_sex,
        "earliest_birth_year": min_year,
        "latest_birth_year": max_year,
        "unique_surnames": len(state.surname_index),
        "top_surnames": [{"surname": s, "count": c} for s, c in top_surnames],
    }


def _get_home_person() -> dict | None:
    """Get the home person (tree owner) record."""
    return _get_individual(state.HOME_PERSON_ID)
