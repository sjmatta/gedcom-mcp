"""
FastMCP3 GEDCOM Genealogy Server

A server that enables querying genealogy data from GEDCOM files.
Optimized for large files (20K+ individuals).
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import FastMCP
from ged4py import GedcomReader

# Configuration
GEDCOM_FILE = Path(__file__).parent / "tree.ged"
HOME_PERSON_ID = "@I370014870784@"  # Stephen John MATTA (1984)

# Initialize FastMCP server
mcp = FastMCP("GEDCOM Genealogy Server")


# Data Models
@dataclass
class Individual:
    id: str
    given_name: str = ""
    surname: str = ""
    sex: str | None = None
    birth_date: str | None = None
    birth_place: str | None = None
    death_date: str | None = None
    death_place: str | None = None
    family_as_child: str | None = None  # FAMC reference
    families_as_spouse: list[str] = field(default_factory=list)  # FAMS references

    def full_name(self) -> str:
        parts = [self.given_name, self.surname]
        return " ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "given_name": self.given_name,
            "surname": self.surname,
            "full_name": self.full_name(),
            "sex": self.sex,
            "birth_date": self.birth_date,
            "birth_place": self.birth_place,
            "death_date": self.death_date,
            "death_place": self.death_place,
            "family_as_child": self.family_as_child,
            "families_as_spouse": self.families_as_spouse,
        }

    def to_summary(self) -> dict:
        """Short summary for list views."""
        return {
            "id": self.id,
            "name": self.full_name(),
            "birth_date": self.birth_date,
            "death_date": self.death_date,
        }


@dataclass
class Family:
    id: str
    husband_id: str | None = None
    wife_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    marriage_date: str | None = None
    marriage_place: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "husband_id": self.husband_id,
            "wife_id": self.wife_id,
            "children_ids": self.children_ids,
            "marriage_date": self.marriage_date,
            "marriage_place": self.marriage_place,
        }


# Global indexes (populated at startup)
individuals: dict[str, Individual] = {}
families: dict[str, Family] = {}
surname_index: dict[str, list[str]] = defaultdict(list)
birth_year_index: dict[int, list[str]] = defaultdict(list)
place_index: dict[str, list[str]] = defaultdict(list)  # place (lowercase) -> individual IDs


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
    except (AttributeError, KeyError):
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
    except (AttributeError, KeyError):
        pass
    return date_val, place_val


def parse_name(record) -> tuple[str, str]:
    """Parse name from GEDCOM record, returning (given_name, surname)."""
    given = ""
    surname = ""
    try:
        name_rec = record.sub_tag("NAME")
        if name_rec and name_rec.value:
            name_str = str(name_rec.value)
            # GEDCOM format: "Given /Surname/"
            if "/" in name_str:
                parts = name_str.split("/")
                given = parts[0].strip()
                if len(parts) > 1:
                    surname = parts[1].strip()
            else:
                given = name_str.strip()
        # Also check for explicit GIVN and SURN tags
        givn = name_rec.sub_tag("GIVN") if name_rec else None
        if givn and givn.value:
            given = str(givn.value)
        surn = name_rec.sub_tag("SURN") if name_rec else None
        if surn and surn.value:
            surname = str(surn.value)
    except (AttributeError, KeyError):
        pass
    return given, surname


def load_gedcom():
    """Parse the GEDCOM file and build indexes."""
    global individuals, families, surname_index, birth_year_index, place_index

    if not GEDCOM_FILE.exists():
        raise FileNotFoundError(f"GEDCOM file not found: {GEDCOM_FILE}")

    with GedcomReader(str(GEDCOM_FILE)) as reader:
        # Parse individuals
        for record in reader.records0("INDI"):
            indi_id = record.xref_id
            given, surname = parse_name(record)
            sex = get_record_value(record, "SEX")
            birth_date, birth_place = get_event_details(record, "BIRT")
            death_date, death_place = get_event_details(record, "DEAT")

            # Get family references
            famc = None
            fams_list = []
            for sub in record.sub_records:
                if sub.tag == "FAMC" and sub.value:
                    famc = normalize_id(sub.value)
                elif sub.tag == "FAMS" and sub.value:
                    fams_list.append(normalize_id(sub.value))

            indi = Individual(
                id=indi_id,  # type: ignore[arg-type]
                given_name=given,
                surname=surname,
                sex=sex,
                birth_date=birth_date,
                birth_place=birth_place,
                death_date=death_date,
                death_place=death_place,
                family_as_child=famc,
                families_as_spouse=fams_list,  # type: ignore[arg-type]
            )
            individuals[indi_id] = indi  # type: ignore[index]

            # Build indexes
            if surname:
                surname_index[surname.lower()].append(indi_id)  # type: ignore[arg-type]

            birth_year = extract_year(birth_date)
            if birth_year:
                birth_year_index[birth_year].append(indi_id)  # type: ignore[arg-type]

            # Index all places
            for place in [birth_place, death_place]:
                if place:
                    place_lower = place.lower()
                    place_index[place_lower].append(indi_id)  # type: ignore[arg-type]

        # Parse families
        for record in reader.records0("FAM"):
            fam_id = record.xref_id
            husb_id = None
            wife_id = None
            child_ids = []

            for sub in record.sub_records:
                if sub.tag == "HUSB" and sub.value:
                    husb_id = normalize_id(sub.value)
                elif sub.tag == "WIFE" and sub.value:
                    wife_id = normalize_id(sub.value)
                elif sub.tag == "CHIL" and sub.value:
                    child_ids.append(normalize_id(sub.value))

            marr_date, marr_place = get_event_details(record, "MARR")

            fam = Family(
                id=fam_id,  # type: ignore[arg-type]
                husband_id=husb_id,
                wife_id=wife_id,
                children_ids=child_ids,  # type: ignore[arg-type]
                marriage_date=marr_date,
                marriage_place=marr_place,
            )
            families[fam_id] = fam  # type: ignore[index]


# Load GEDCOM at module import time
load_gedcom()


# ============== CORE LOGIC FUNCTIONS ==============
# These are the actual implementations, separate from MCP decorators


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

    for indi in individuals.values():
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
    indi = individuals.get(lookup_id)
    return indi.to_dict() if indi else None


def _get_family(family_id: str) -> dict | None:
    lookup_id = _normalize_lookup_id(family_id)
    fam = families.get(lookup_id)
    if not fam:
        return None

    result = fam.to_dict()

    # Add names for convenience
    if fam.husband_id and fam.husband_id in individuals:
        result["husband_name"] = individuals[fam.husband_id].full_name()
    if fam.wife_id and fam.wife_id in individuals:
        result["wife_name"] = individuals[fam.wife_id].full_name()

    result["children"] = []
    for child_id in fam.children_ids:
        if child_id in individuals:
            result["children"].append(individuals[child_id].to_summary())

    return result


def _get_parents(individual_id: str) -> dict | None:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
    if not indi or not indi.family_as_child:
        return None

    fam = families.get(indi.family_as_child)
    if not fam:
        return None

    result = {"family_id": fam.id, "father": None, "mother": None}

    if fam.husband_id and fam.husband_id in individuals:
        result["father"] = individuals[fam.husband_id].to_dict()  # type: ignore[assignment]
    if fam.wife_id and fam.wife_id in individuals:
        result["mother"] = individuals[fam.wife_id].to_dict()  # type: ignore[assignment]

    return result


def _get_children(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
    if not indi:
        return []

    children = []
    seen = set()

    for fam_id in indi.families_as_spouse:
        fam = families.get(fam_id)
        if fam:
            for child_id in fam.children_ids:
                if child_id not in seen and child_id in individuals:
                    seen.add(child_id)
                    children.append(individuals[child_id].to_summary())

    return children


def _get_spouses(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
    if not indi:
        return []

    spouses = []

    for fam_id in indi.families_as_spouse:
        fam = families.get(fam_id)
        if fam:
            spouse_id = fam.wife_id if fam.husband_id == lookup_id else fam.husband_id
            if spouse_id and spouse_id in individuals:
                spouse_info = individuals[spouse_id].to_summary()
                spouse_info["family_id"] = fam_id
                spouse_info["marriage_date"] = fam.marriage_date
                spouse_info["marriage_place"] = fam.marriage_place
                spouses.append(spouse_info)

    return spouses


def _get_siblings(individual_id: str) -> list[dict]:
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
    if not indi or not indi.family_as_child:
        return []

    fam = families.get(indi.family_as_child)
    if not fam:
        return []

    siblings = []
    for child_id in fam.children_ids:
        if child_id != lookup_id and child_id in individuals:
            siblings.append(individuals[child_id].to_summary())

    return siblings


def _get_ancestors(individual_id: str, generations: int = 4) -> dict:
    lookup_id = _normalize_lookup_id(individual_id)
    generations = min(generations, 10)  # Cap at 10 to prevent huge responses

    def build_ancestor_tree(indi_id: str | None, gen: int) -> dict | None:
        if not indi_id or gen <= 0 or indi_id not in individuals:
            return None

        indi = individuals[indi_id]
        result = indi.to_summary()

        if gen > 1 and indi.family_as_child:
            fam = families.get(indi.family_as_child)
            if fam:
                result["father"] = build_ancestor_tree(fam.husband_id, gen - 1)
                result["mother"] = build_ancestor_tree(fam.wife_id, gen - 1)

        return result

    return build_ancestor_tree(lookup_id, generations + 1) or {}


def _get_descendants(individual_id: str, generations: int = 4) -> dict:
    lookup_id = _normalize_lookup_id(individual_id)
    generations = min(generations, 10)

    def build_descendant_tree(indi_id: str | None, gen: int) -> dict | None:
        if not indi_id or gen <= 0 or indi_id not in individuals:
            return None

        indi = individuals[indi_id]
        result = indi.to_summary()

        if gen > 1:
            children_list = []
            for fam_id in indi.families_as_spouse:
                fam = families.get(fam_id)
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
    year: int | None = None, place: str | None = None, year_range: int = 5, max_results: int = 50
) -> list[dict]:
    results = []
    candidates = set()

    if year:
        for y in range(year - year_range, year + year_range + 1):
            candidates.update(birth_year_index.get(y, []))
    else:
        candidates = set(individuals.keys())

    place_lower = place.lower() if place else None

    for indi_id in candidates:
        indi = individuals.get(indi_id)
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
    for indexed_place, indi_ids in place_index.items():
        if place_lower in indexed_place:
            for indi_id in indi_ids:
                if indi_id not in seen and indi_id in individuals:
                    seen.add(indi_id)
                    indi = individuals[indi_id]
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
    birth_years = list(birth_year_index.keys())
    min_year = min(birth_years) if birth_years else None
    max_year = max(birth_years) if birth_years else None

    # Count by sex
    males = sum(1 for i in individuals.values() if i.sex == "M")
    females = sum(1 for i in individuals.values() if i.sex == "F")
    unknown_sex = len(individuals) - males - females

    # Top surnames
    surname_counts = [(surname, len(ids)) for surname, ids in surname_index.items()]
    surname_counts.sort(key=lambda x: -x[1])
    top_surnames = surname_counts[:20]

    return {
        "total_individuals": len(individuals),
        "total_families": len(families),
        "males": males,
        "females": females,
        "unknown_sex": unknown_sex,
        "earliest_birth_year": min_year,
        "latest_birth_year": max_year,
        "unique_surnames": len(surname_index),
        "top_surnames": [{"surname": s, "count": c} for s, c in top_surnames],
    }


def _get_home_person() -> dict | None:
    """Get the home person (tree owner) record."""
    return _get_individual(HOME_PERSON_ID)


# ============== MCP TOOLS ==============


@mcp.tool()
def get_home_person() -> dict | None:
    """
    Get the home person (tree owner) - Stephen John Matta (1984).

    This is a convenience function to quickly access the primary person in the tree.

    Returns:
        Full individual record for the home person
    """
    return _get_home_person()


@mcp.tool()
def search_individuals(name: str, max_results: int = 50) -> list[dict]:
    """
    Search for individuals by name (partial match on given name or surname).

    Args:
        name: Name to search for (case-insensitive partial match)
        max_results: Maximum number of results to return (default 50)

    Returns:
        List of matching individuals with summary info
    """
    return _search_individuals(name, max_results)


@mcp.tool()
def get_individual(individual_id: str) -> dict | None:
    """
    Get full details for an individual by their GEDCOM ID.

    Args:
        individual_id: The GEDCOM ID (e.g., "I123" or "@I123@")

    Returns:
        Full individual record or None if not found
    """
    return _get_individual(individual_id)


@mcp.tool()
def get_family(family_id: str) -> dict | None:
    """
    Get family information by GEDCOM family ID.

    Args:
        family_id: The GEDCOM family ID (e.g., "F123" or "@F123@")

    Returns:
        Family record with husband, wife, children IDs and marriage info
    """
    return _get_family(family_id)


@mcp.tool()
def get_parents(individual_id: str) -> dict | None:
    """
    Get the parents of an individual.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        Dictionary with father and mother info, or None if not found
    """
    return _get_parents(individual_id)


@mcp.tool()
def get_children(individual_id: str) -> list[dict]:
    """
    Get all children of an individual (from all marriages/partnerships).

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of children with summary info
    """
    return _get_children(individual_id)


@mcp.tool()
def get_spouses(individual_id: str) -> list[dict]:
    """
    Get all spouses/partners of an individual.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of spouses with summary info and marriage details
    """
    return _get_spouses(individual_id)


@mcp.tool()
def get_siblings(individual_id: str) -> list[dict]:
    """
    Get siblings of an individual (same parents).

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of siblings with summary info
    """
    return _get_siblings(individual_id)


@mcp.tool()
def get_ancestors(individual_id: str, generations: int = 4) -> dict:
    """
    Get ancestor tree up to N generations.

    Args:
        individual_id: The GEDCOM ID of the individual
        generations: Number of generations to retrieve (default 4, max 10)

    Returns:
        Nested dictionary representing the ancestor tree
    """
    return _get_ancestors(individual_id, generations)


@mcp.tool()
def get_descendants(individual_id: str, generations: int = 4) -> dict:
    """
    Get descendant tree up to N generations.

    Args:
        individual_id: The GEDCOM ID of the individual
        generations: Number of generations to retrieve (default 4, max 10)

    Returns:
        Nested dictionary representing the descendant tree
    """
    return _get_descendants(individual_id, generations)


@mcp.tool()
def search_by_birth(
    year: int | None = None, place: str | None = None, year_range: int = 5, max_results: int = 50
) -> list[dict]:
    """
    Search individuals by birth year and/or place.

    Args:
        year: Birth year to search for
        place: Birth place to search for (partial match)
        year_range: Years to search around the given year (default 5)
        max_results: Maximum number of results (default 50)

    Returns:
        List of matching individuals
    """
    return _search_by_birth(year, place, year_range, max_results)


@mcp.tool()
def search_by_place(place: str, max_results: int = 50) -> list[dict]:
    """
    Search individuals by any place (birth, death, or residence).

    Args:
        place: Place name to search for (partial match, case-insensitive)
        max_results: Maximum number of results (default 50)

    Returns:
        List of matching individuals with place context
    """
    return _search_by_place(place, max_results)


@mcp.tool()
def get_statistics() -> dict:
    """
    Get statistics about the genealogy tree.

    Returns:
        Dictionary with counts, date ranges, and other statistics
    """
    return _get_statistics()


# ============== RESOURCES ==============


@mcp.resource("gedcom://individual/{id}")
def resource_individual(id: str) -> str:
    """Get individual record by ID."""
    indi = _get_individual(id)
    if indi:
        return str(indi)
    return f"Individual {id} not found"


@mcp.resource("gedcom://family/{id}")
def resource_family(id: str) -> str:
    """Get family record by ID."""
    fam = _get_family(id)
    if fam:
        return str(fam)
    return f"Family {id} not found"


@mcp.resource("gedcom://stats")
def resource_stats() -> str:
    """Get tree statistics."""
    return str(_get_statistics())


@mcp.resource("gedcom://surnames")
def resource_surnames() -> str:
    """Get list of all surnames with counts."""
    surname_counts = [(surname, len(ids)) for surname, ids in surname_index.items()]
    surname_counts.sort(key=lambda x: (-x[1], x[0]))  # Sort by count desc, then name
    return "\n".join(f"{surname}: {count}" for surname, count in surname_counts)


# Entry point
if __name__ == "__main__":
    mcp.run()
