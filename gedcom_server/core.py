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


def _get_ancestors(
    individual_id: str,
    generations: int = 4,
    filter: str | None = None,
) -> dict | list[dict]:
    """Get ancestor tree up to N generations.

    Args:
        individual_id: The GEDCOM ID of the individual
        generations: Number of generations to retrieve (default 4, max 20)
        filter: Optional filter:
            - None: Return full nested tree (default)
            - "terminal": Return only end-of-line ancestors (no known parents)

    Returns:
        If filter is None: Nested dictionary representing the ancestor tree
        If filter is "terminal": List of terminal (brick wall) ancestors
    """
    lookup_id = _normalize_lookup_id(individual_id)
    generations = min(generations, 20)  # Cap at 20

    if filter == "terminal":
        # Find ancestors with no known parents (brick walls)
        terminal_ancestors: list[dict] = []
        seen: set[str] = set()

        def find_terminal(indi_id: str | None, gen: int, path: list[str]) -> None:
            if not indi_id or gen <= 0 or indi_id not in state.individuals:
                return
            if indi_id in seen:
                return
            seen.add(indi_id)

            indi = state.individuals[indi_id]

            # Check if this person has parents
            has_parents = False
            if indi.family_as_child:
                fam = state.families.get(indi.family_as_child)
                if fam and (fam.husband_id or fam.wife_id):
                    has_parents = True
                    # Recurse to parents
                    if fam.husband_id:
                        find_terminal(fam.husband_id, gen - 1, path + ["father"])
                    if fam.wife_id:
                        find_terminal(fam.wife_id, gen - 1, path + ["mother"])

            if not has_parents and indi_id != lookup_id:
                result = indi.to_summary()
                result["generation"] = generations - gen + 1
                result["path"] = path
                terminal_ancestors.append(result)

        find_terminal(lookup_id, generations + 1, [])
        return terminal_ancestors

    # Default: return nested tree
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


def _get_surname_group(surname: str, include_spouses: bool = False) -> dict:
    """Get all individuals with a surname plus summary statistics.

    Args:
        surname: Surname to look up (case-insensitive)
        include_spouses: If True, also include spouses of surname group members

    Returns:
        Dict with surname, count, individuals list, and statistics
    """
    from .helpers import extract_year

    surname_lower = surname.lower()
    indi_ids = state.surname_index.get(surname_lower, [])

    # Collect individuals
    individuals_data: list[dict] = []
    spouse_ids: set[str] = set()

    for indi_id in indi_ids:
        indi = state.individuals.get(indi_id)
        if indi:
            individuals_data.append(indi.to_summary())
            # Collect spouse IDs if requested
            if include_spouses:
                for fam_id in indi.families_as_spouse:
                    fam = state.families.get(fam_id)
                    if fam:
                        spouse_id = fam.wife_id if fam.husband_id == indi_id else fam.husband_id
                        if spouse_id and spouse_id not in indi_ids:
                            spouse_ids.add(spouse_id)

    # Add spouses if requested
    if include_spouses:
        for spouse_id in spouse_ids:
            spouse = state.individuals.get(spouse_id)
            if spouse:
                spouse_data = spouse.to_summary()
                spouse_data["is_spouse"] = True
                individuals_data.append(spouse_data)

    # Compute statistics
    birth_years: list[int] = []
    places: list[str] = []

    for indi_id in indi_ids:
        indi = state.individuals.get(indi_id)
        if indi:
            if indi.birth_date:
                year = extract_year(indi.birth_date)
                if year:
                    birth_years.append(year)
            if indi.birth_place:
                places.append(indi.birth_place)

    # Count common places
    place_counts: dict[str, int] = {}
    for place in places:
        place_counts[place] = place_counts.get(place, 0) + 1
    common_places = sorted(place_counts.items(), key=lambda x: -x[1])[:5]

    # Estimate generation count from birth year spread
    if birth_years:
        year_span = max(birth_years) - min(birth_years)
        generation_count = max(1, year_span // 25 + 1)
    else:
        generation_count = 0

    return {
        "surname": surname,
        "count": len(indi_ids),
        "individuals": individuals_data,
        "statistics": {
            "earliest_birth": min(birth_years) if birth_years else None,
            "latest_birth": max(birth_years) if birth_years else None,
            "common_places": [{"place": p, "count": c} for p, c in common_places],
            "generation_count": generation_count,
        },
    }


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
    if state.HOME_PERSON_ID is None:
        return None
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


def _get_relationship(id1: str, id2: str, max_generations: int | None = 10) -> dict:
    """Calculate and name the relationship between two individuals.

    Args:
        id1: GEDCOM ID of first individual
        id2: GEDCOM ID of second individual
        max_generations: How far back to search (default 10, None = unlimited)

    Returns:
        Dict with relationship info including relationship name
    """
    lookup_id1 = _normalize_lookup_id(id1)
    lookup_id2 = _normalize_lookup_id(id2)

    # Use a very large number for "unlimited" to avoid changing traversal logic
    search_depth = max_generations if max_generations is not None else 100

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

    # Check deep direct ancestry (beyond grandparent)
    # Build ancestor set for id1 and check if id2 is in it
    ancestors1 = _build_ancestor_set(lookup_id1, search_depth)
    if lookup_id2 in ancestors1:
        gen = min(ancestors1[lookup_id2])
        return {**base_result, "relationship": _ancestor_name(gen)}

    # Check if id1 is a direct ancestor of id2
    ancestors2 = _build_ancestor_set(lookup_id2, search_depth)
    if lookup_id1 in ancestors2:
        gen = min(ancestors2[lookup_id1])
        return {**base_result, "relationship": _descendant_name(gen)}

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

    # Check cousins via common ancestors (reuse already-built ancestor sets)
    common_ids = set(ancestors1.keys()) & set(ancestors2.keys())

    if common_ids:
        # Find closest common ancestor
        closest_id = None
        closest_gen1 = 0
        closest_gen2 = 0
        min_total_gen = float("inf")
        for ancestor_id in common_ids:
            gen1 = min(ancestors1[ancestor_id])
            gen2 = min(ancestors2[ancestor_id])
            total = gen1 + gen2
            if total < min_total_gen:
                min_total_gen = total
                closest_id = ancestor_id
                closest_gen1 = gen1
                closest_gen2 = gen2

        if closest_id:
            # Cousin calculation
            # First cousins share grandparents (gen 2 for both)
            # Second cousins share great-grandparents (gen 3 for both)
            cousin_degree = min(closest_gen1, closest_gen2) - 1
            removal = abs(closest_gen1 - closest_gen2)

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

                ancestor = state.individuals.get(closest_id)
                return {
                    **base_result,
                    "relationship": rel,
                    "common_ancestor": {
                        "id": closest_id,
                        "name": ancestor.full_name() if ancestor else None,
                    },
                }

    depth_msg = f"within {search_depth} generations" if max_generations else "in tree"
    return {**base_result, "relationship": f"not related ({depth_msg})"}


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


def _ancestor_name(gen: int) -> str:
    """Convert generation distance to ancestor relationship name.

    gen 1 = parent
    gen 2 = grandparent
    gen 3 = great-grandparent
    gen 4 = 2nd great-grandparent
    gen 5 = 3rd great-grandparent, etc.
    """
    if gen == 1:
        return "parent"
    if gen == 2:
        return "grandparent"
    if gen == 3:
        return "great-grandparent"
    # gen 4 = 2nd great-grandparent, gen 5 = 3rd, etc.
    return f"{_ordinal(gen - 2)} great-grandparent"


def _descendant_name(gen: int) -> str:
    """Convert generation distance to descendant relationship name.

    gen 1 = child
    gen 2 = grandchild
    gen 3 = great-grandchild
    gen 4 = 2nd great-grandchild, etc.
    """
    if gen == 1:
        return "child"
    if gen == 2:
        return "grandchild"
    if gen == 3:
        return "great-grandchild"
    return f"{_ordinal(gen - 2)} great-grandchild"


def _get_relationship_matrix(individual_ids: list[str]) -> dict:
    """Calculate all pairwise relationships for a group of individuals.

    Efficiently computes N×(N-1)/2 relationships by building ancestor sets once
    and reusing them for all comparisons.

    Args:
        individual_ids: List of GEDCOM IDs to calculate relationships between

    Returns:
        Dict with individuals list and relationships matrix
    """
    # Normalize IDs and validate
    normalized_ids: list[str] = []
    individuals_info: list[dict] = []

    for id_str in individual_ids:
        lookup_id = _normalize_lookup_id(id_str)
        indi = state.individuals.get(lookup_id)
        if indi:
            normalized_ids.append(lookup_id)
            individuals_info.append({"id": lookup_id, "name": indi.full_name()})

    # Build ancestor sets for all individuals once
    ancestor_cache: dict[str, dict[str, list[int]]] = {}
    for indi_id in normalized_ids:
        ancestor_cache[indi_id] = _build_ancestor_set(indi_id, max_generations=10)

    # Calculate pairwise relationships
    relationships: list[dict] = []
    for i, id1 in enumerate(normalized_ids):
        for id2 in normalized_ids[i + 1 :]:
            rel_info = _get_relationship_with_cache(id1, id2, ancestor_cache)
            relationships.append(
                {
                    "id1": id1,
                    "id2": id2,
                    "relationship": rel_info.get("relationship"),
                }
            )

    return {
        "individuals": individuals_info,
        "relationships": relationships,
        "pair_count": len(relationships),
    }


def _get_relationship_with_cache(
    id1: str, id2: str, ancestor_cache: dict[str, dict[str, list[int]]]
) -> dict:
    """Calculate relationship using pre-computed ancestor cache.

    This is an optimized version of _get_relationship that uses cached ancestor sets.
    """
    indi1 = state.individuals.get(id1)
    indi2 = state.individuals.get(id2)

    base_result = {
        "individual_1": {"id": id1, "name": indi1.full_name() if indi1 else None},
        "individual_2": {"id": id2, "name": indi2.full_name() if indi2 else None},
    }

    if not indi1 or not indi2:
        return {**base_result, "relationship": None}

    # Check identity
    if id1 == id2:
        return {**base_result, "relationship": "same person"}

    # Check direct parent/child
    if indi1.family_as_child:
        fam = state.families.get(indi1.family_as_child)
        if fam and id2 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "child"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam and id1 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "parent"}

    # Check spouse
    for fam_id in indi1.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam and id2 in (fam.husband_id, fam.wife_id):
            return {**base_result, "relationship": "spouse"}

    # Check sibling (full or half)
    if indi1.family_as_child and indi2.family_as_child:
        fam1 = state.families.get(indi1.family_as_child)
        fam2 = state.families.get(indi2.family_as_child)
        if fam1 and fam2:
            if fam1.id == fam2.id:
                return {**base_result, "relationship": "sibling"}
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
                        if gp_fam and id2 in (gp_fam.husband_id, gp_fam.wife_id):
                            return {**base_result, "relationship": "grandchild"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and id1 in (gp_fam.husband_id, gp_fam.wife_id):
                            return {**base_result, "relationship": "grandparent"}

    # Check deep direct ancestry (beyond grandparent) using cached ancestors
    ancestors1 = ancestor_cache.get(id1, {})
    if id2 in ancestors1:
        gen = min(ancestors1[id2])
        return {**base_result, "relationship": _ancestor_name(gen)}

    ancestors2 = ancestor_cache.get(id2, {})
    if id1 in ancestors2:
        gen = min(ancestors2[id1])
        return {**base_result, "relationship": _descendant_name(gen)}

    # Check aunt/uncle and niece/nephew
    if indi1.family_as_child:
        fam = state.families.get(indi1.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and id2 in gp_fam.children_ids:
                            return {**base_result, "relationship": "niece/nephew"}

    if indi2.family_as_child:
        fam = state.families.get(indi2.family_as_child)
        if fam:
            for parent_id in [fam.husband_id, fam.wife_id]:
                if parent_id:
                    parent = state.individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        gp_fam = state.families.get(parent.family_as_child)
                        if gp_fam and id1 in gp_fam.children_ids:
                            return {**base_result, "relationship": "aunt/uncle"}

    # Check cousins via cached ancestor data (reuse already-fetched ancestors)
    common_ids = set(ancestors1.keys()) & set(ancestors2.keys())

    if common_ids:
        # Find closest common ancestor
        closest = None
        min_total_gen = float("inf")
        for ancestor_id in common_ids:
            gen1 = min(ancestors1[ancestor_id])
            gen2 = min(ancestors2[ancestor_id])
            total = gen1 + gen2
            if total < min_total_gen:
                min_total_gen = total
                closest = (ancestor_id, gen1, gen2)

        if closest:
            _, gen1, gen2 = closest
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
                return {**base_result, "relationship": rel}

    return {**base_result, "relationship": "not related (within 10 generations)"}


def _traverse(
    individual_id: str,
    direction: str,
    depth: int = 1,
) -> list[dict]:
    """Generic graph traversal for advanced queries.

    Args:
        individual_id: Starting person's GEDCOM ID
        direction: "parents" | "children" | "spouses" | "siblings"
        depth: How many levels to traverse (default 1, max 10)

    Returns:
        List of individuals at each level, with a "level" field indicating depth
    """
    lookup_id = _normalize_lookup_id(individual_id)
    depth = min(max(depth, 1), 10)  # Clamp between 1 and 10

    results: list[dict] = []
    seen: set[str] = {lookup_id}  # Track visited to avoid cycles

    def get_related(indi_id: str, dir_type: str) -> list[str]:
        """Get related individual IDs for a given direction."""
        indi = state.individuals.get(indi_id)
        if not indi:
            return []

        related_ids: list[str] = []

        if dir_type == "parents":
            if indi.family_as_child:
                fam = state.families.get(indi.family_as_child)
                if fam:
                    if fam.husband_id and fam.husband_id in state.individuals:
                        related_ids.append(fam.husband_id)
                    if fam.wife_id and fam.wife_id in state.individuals:
                        related_ids.append(fam.wife_id)

        elif dir_type == "children":
            for fam_id in indi.families_as_spouse:
                fam = state.families.get(fam_id)
                if fam:
                    for child_id in fam.children_ids:
                        if child_id in state.individuals:
                            related_ids.append(child_id)

        elif dir_type == "spouses":
            for fam_id in indi.families_as_spouse:
                fam = state.families.get(fam_id)
                if fam:
                    spouse_id = fam.wife_id if fam.husband_id == indi_id else fam.husband_id
                    if spouse_id and spouse_id in state.individuals:
                        related_ids.append(spouse_id)

        elif dir_type == "siblings" and indi.family_as_child:
            fam = state.families.get(indi.family_as_child)
            if fam:
                for child_id in fam.children_ids:
                    if child_id != indi_id and child_id in state.individuals:
                        related_ids.append(child_id)

        return related_ids

    # BFS traversal
    current_level = [lookup_id]
    for level in range(1, depth + 1):
        next_level: list[str] = []
        for indi_id in current_level:
            for related_id in get_related(indi_id, direction):
                if related_id not in seen:
                    seen.add(related_id)
                    next_level.append(related_id)
                    indi = state.individuals[related_id]
                    result = indi.to_summary()
                    result["level"] = level
                    results.append(result)
        current_level = next_level
        if not current_level:
            break

    return results


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
