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


def _get_individuals_batch(individual_ids: list[str]) -> dict[str, dict | None]:
    """Get multiple individuals efficiently in one call.

    Args:
        individual_ids: List of GEDCOM IDs to retrieve

    Returns:
        Dict mapping ID → individual data (or None if not found)
    """
    results = {}
    for id_str in individual_ids:
        lookup_id = _normalize_lookup_id(id_str)
        indi = state.individuals.get(lookup_id)
        results[lookup_id] = indi.to_dict() if indi else None
    return results


def _build_ancestor_set(individual_id: str, max_generations: int = 10) -> dict[str, list[int]]:
    """Build a set of all ancestors with their generation depths.

    Returns dict mapping ancestor_id -> list of generation distances
    (list because ancestor may appear multiple times via different paths).
    """
    lookup_id = _normalize_lookup_id(individual_id)
    ancestors: dict[str, list[int]] = {}

    def traverse(indi_id: str | None, generation: int) -> None:
        if not indi_id or generation > max_generations:
            return
        if indi_id not in state.individuals:
            return

        indi = state.individuals[indi_id]
        if not indi.family_as_child:
            return

        fam = state.families.get(indi.family_as_child)
        if not fam:
            return

        for parent_id in [fam.husband_id, fam.wife_id]:
            if parent_id and parent_id in state.individuals:
                if parent_id not in ancestors:
                    ancestors[parent_id] = []
                ancestors[parent_id].append(generation)
                traverse(parent_id, generation + 1)

    traverse(lookup_id, 1)
    return ancestors


def _find_common_ancestors(id1: str, id2: str, max_generations: int = 10) -> dict:
    """Find common ancestors between two individuals.

    Args:
        id1: GEDCOM ID of first individual
        id2: GEDCOM ID of second individual
        max_generations: Max generations to search (default 10)

    Returns:
        Dict with individual info and list of common ancestors with generation info
    """
    lookup_id1 = _normalize_lookup_id(id1)
    lookup_id2 = _normalize_lookup_id(id2)

    indi1 = state.individuals.get(lookup_id1)
    indi2 = state.individuals.get(lookup_id2)

    if not indi1 or not indi2:
        return {
            "individual_1": {"id": lookup_id1, "name": indi1.full_name() if indi1 else None},
            "individual_2": {"id": lookup_id2, "name": indi2.full_name() if indi2 else None},
            "common_ancestors": [],
            "error": "One or both individuals not found",
        }

    # Build ancestor sets for both individuals
    ancestors1 = _build_ancestor_set(lookup_id1, max_generations)
    ancestors2 = _build_ancestor_set(lookup_id2, max_generations)

    # Find intersection
    common_ids = set(ancestors1.keys()) & set(ancestors2.keys())

    common_ancestors: list[dict[str, str | int]] = []
    for ancestor_id in common_ids:
        ancestor = state.individuals.get(ancestor_id)
        if ancestor:
            gen1 = min(ancestors1[ancestor_id])
            gen2 = min(ancestors2[ancestor_id])
            common_ancestors.append(
                {
                    "id": ancestor_id,
                    "name": ancestor.full_name(),
                    "generations_from_1": gen1,
                    "generations_from_2": gen2,
                }
            )

    # Sort by total generation distance
    common_ancestors.sort(key=lambda x: int(x["generations_from_1"]) + int(x["generations_from_2"]))

    return {
        "individual_1": {"id": lookup_id1, "name": indi1.full_name()},
        "individual_2": {"id": lookup_id2, "name": indi2.full_name()},
        "common_ancestors": common_ancestors,
    }


def _get_relationship(id1: str, id2: str) -> dict:
    """Calculate and name the relationship between two individuals.

    Args:
        id1: GEDCOM ID of first individual
        id2: GEDCOM ID of second individual

    Returns:
        Dict with relationship info including relationship name
    """
    lookup_id1 = _normalize_lookup_id(id1)
    lookup_id2 = _normalize_lookup_id(id2)

    indi1 = state.individuals.get(lookup_id1)
    indi2 = state.individuals.get(lookup_id2)

    base_result = {
        "individual_1": {"id": lookup_id1, "name": indi1.full_name() if indi1 else None},
        "individual_2": {"id": lookup_id2, "name": indi2.full_name() if indi2 else None},
    }

    if not indi1 or not indi2:
        return {**base_result, "relationship": None, "error": "One or both individuals not found"}

    # Check identity
    if lookup_id1 == lookup_id2:
        return {**base_result, "relationship": "same person"}

    # Check direct parent/child
    if indi1.family_as_child:
        fam = state.families.get(indi1.family_as_child)
        if fam and lookup_id2 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "child"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam and lookup_id1 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "parent"}

    # Check spouse
    for fam_id in indi1.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam and lookup_id2 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "spouse"}

    # Check sibling (full or half)
    if indi1.family_as_child and indi2.family_as_child:
        fam1 = state.families.get(indi1.family_as_child)
        fam2 = state.families.get(indi2.family_as_child)
        if fam1 and fam2:
            if fam1.id == fam2.id:
                return {**base_result, "relationship": "sibling"}
            # Check half-sibling
            parents1 = {fam1.husband_id, fam1.wife_id} - {None}
            parents2 = {fam2.husband_id, fam2.wife_id} - {None}
            if parents1 & parents2:
                return {**base_result, "relationship": "half-sibling"}

    # Check grandparent/grandchild
    if indi1.family_as_child:
        fam = state.families.get(indi1.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and lookup_id2 in (gp_fam.husband_id, gp_fam.wife_id):
                            return {**base_result, "relationship": "grandchild"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and lookup_id1 in (gp_fam.husband_id, gp_fam.wife_id):
                            return {**base_result, "relationship": "grandparent"}

    # Check aunt/uncle and niece/nephew
    # id2 is aunt/uncle of id1 if id2 is sibling of id1's parent
    if indi1.family_as_child:
        fam = state.families.get(indi1.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and lookup_id2 in gp_fam.children_ids:
                            return {**base_result, "relationship": "niece/nephew"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and lookup_id1 in gp_fam.children_ids:
                            return {**base_result, "relationship": "aunt/uncle"}

    # Check cousins via common ancestors
    common = _find_common_ancestors(lookup_id1, lookup_id2, max_generations=10)
    if common["common_ancestors"]:
        # Use closest common ancestor
        closest = common["common_ancestors"][0]
        gen1 = closest["generations_from_1"]
        gen2 = closest["generations_from_2"]

        # Cousin calculation
        # First cousins share grandparents (gen 2 for both)
        # Second cousins share great-grandparents (gen 3 for both)
        cousin_degree = min(gen1, gen2) - 1
        removal = abs(gen1 - gen2)

        if cousin_degree >= 1:
            ordinal = _ordinal(cousin_degree)
            if removal == 0:
                rel = f"{ordinal} cousin"
            elif removal == 1:
                rel = f"{ordinal} cousin once removed"
            elif removal == 2:
                rel = f"{ordinal} cousin twice removed"
            else:
                rel = f"{ordinal} cousin {removal}x removed"

            return {
                **base_result,
                "relationship": rel,
                "common_ancestor": {"id": closest["id"], "name": closest["name"]},
            }

    return {**base_result, "relationship": "not related (within 10 generations)"}


def _ordinal(n: int) -> str:
    """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
    ordinals = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
    }
    return ordinals.get(n, f"{n}th")


def _detect_pedigree_collapse(individual_id: str, max_generations: int = 10) -> dict:
    """Detect pedigree collapse (ancestors appearing multiple times).

    Args:
        individual_id: GEDCOM ID of the individual
        max_generations: Max generations to search (default 10)

    Returns:
        Dict with collapse points showing ancestors appearing multiple times
    """
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)

    if not indi:
        return {
            "individual": {"id": lookup_id, "name": None},
            "collapse_points": [],
            "error": "Individual not found",
        }

    # Track all paths to each ancestor
    ancestor_paths: dict[str, list[list[str]]] = {}

    def traverse(indi_id: str, path: list[str], generation: int) -> None:
        if generation > max_generations:
            return
        if indi_id not in state.individuals:
            return

        current_indi = state.individuals[indi_id]
        if not current_indi.family_as_child:
            return

        fam = state.families.get(current_indi.family_as_child)
        if not fam:
            return

        for parent_id in [fam.husband_id, fam.wife_id]:
            if parent_id and parent_id in state.individuals:
                new_path = path + [parent_id]
                if parent_id not in ancestor_paths:
                    ancestor_paths[parent_id] = []
                ancestor_paths[parent_id].append(new_path)
                traverse(parent_id, new_path, generation + 1)

    traverse(lookup_id, [lookup_id], 1)

    # Find collapse points (ancestors with multiple paths)
    # Store occurrence_count separately for sorting
    collapse_data: list[tuple[int, dict]] = []
    for ancestor_id, paths in ancestor_paths.items():
        if len(paths) > 1:
            ancestor = state.individuals.get(ancestor_id)
            if ancestor:
                occurrence_count = len(paths)
                collapse_data.append(
                    (
                        occurrence_count,
                        {
                            "ancestor_id": ancestor_id,
                            "ancestor_name": ancestor.full_name(),
                            "paths": paths,
                            "generations": [len(p) - 1 for p in paths],
                            "occurrence_count": occurrence_count,
                        },
                    )
                )

    # Sort by occurrence count (most collapsed first)
    collapse_data.sort(key=lambda x: -x[0])
    collapse_points = [item[1] for item in collapse_data]

    return {
        "individual": {"id": lookup_id, "name": indi.full_name()},
        "collapse_points": collapse_points,
        "total_collapse_ancestors": len(collapse_points),
    }
