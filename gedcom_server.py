"""
FastMCP3 GEDCOM Genealogy Server

A server that enables querying genealogy data from GEDCOM files.
Optimized for large files (20K+ individuals).
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import geonamescache
import jellyfish
from fastmcp import FastMCP
from ged4py import GedcomReader
from haversine import Unit, haversine
from rapidfuzz import fuzz, process

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
    events: list["Event"] = field(default_factory=list)  # All life events
    notes: list[str] = field(default_factory=list)  # Biographical notes

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
            "notes": self.notes,
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


@dataclass
class Source:
    id: str
    title: str | None = None
    author: str | None = None
    publication: str | None = None
    repository_id: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "publication": self.publication,
            "repository_id": self.repository_id,
            "note": self.note,
        }

    def to_summary(self) -> dict:
        """Short summary for list views."""
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
        }


@dataclass
class Citation:
    source_id: str
    source_title: str | None = None
    page: str | None = None
    text: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "page": self.page,
            "text": self.text,
            "url": self.url,
        }


@dataclass
class Repository:
    id: str
    name: str | None = None
    address: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "url": self.url,
        }


@dataclass
class Event:
    type: str  # BIRT, DEAT, RESI, OCCU, IMMI, etc.
    date: str | None = None
    place: str | None = None
    description: str | None = None  # For EVEN type records
    citations: list[Citation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "date": self.date,
            "place": self.place,
            "description": self.description,
            "citations": [c.to_dict() for c in self.citations],
            "notes": self.notes,
        }


@dataclass
class Place:
    """A unique place with normalized form and optional coordinates."""

    id: str  # Hash of original string
    original: str  # Original GEDCOM value
    normalized: str  # Cleaned/standardized form
    components: list[str] = field(default_factory=list)  # [city, county, state, country]
    latitude: float | None = None
    longitude: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original": self.original,
            "normalized": self.normalized,
            "components": self.components,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    def to_summary(self) -> dict:
        """Short summary for list views."""
        return {
            "id": self.id,
            "original": self.original,
            "normalized": self.normalized,
        }


# Global indexes (populated at startup)
individuals: dict[str, Individual] = {}
families: dict[str, Family] = {}
sources: dict[str, Source] = {}
repositories: dict[str, Repository] = {}
surname_index: dict[str, list[str]] = defaultdict(list)
birth_year_index: dict[int, list[str]] = defaultdict(list)
place_index: dict[str, list[str]] = defaultdict(list)  # place (lowercase) -> individual IDs

# Place indexes for fuzzy search and geocoding
places: dict[str, Place] = {}  # place_id -> Place
individual_places: dict[str, list[str]] = defaultdict(list)  # individual_id -> list of place_ids


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


# Event tags to parse from individuals
EVENT_TAGS = ["BIRT", "DEAT", "RESI", "OCCU", "EVEN", "IMMI", "CENS", "NATU"]

# Place normalization - common abbreviations
PLACE_ABBREVIATIONS = {
    "st.": "saint",
    "st ": "saint ",
    "co.": "county",
    "co ": "county ",
    "mt.": "mount",
    "mt ": "mount ",
    "ft.": "fort",
    "ft ": "fort ",
    "n.y.": "new york",
    "n.y": "new york",
    "nyc": "new york city",
    "l.a.": "los angeles",
    "d.c.": "district of columbia",
    "u.s.a.": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "u.k.": "united kingdom",
    "uk": "united kingdom",
}

# Historical place name mappings (bidirectional)
HISTORICAL_NAMES = {
    # Cities that have been renamed
    "constantinople": "istanbul",
    "kristiania": "oslo",
    "petrograd": "saint petersburg",
    "leningrad": "saint petersburg",
    "saigon": "ho chi minh city",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
    "peking": "beijing",
    "canton": "guangzhou",
    "rangoon": "yangon",
    "batavia": "jakarta",
    "danzig": "gdansk",
    "breslau": "wroclaw",
    "konigsberg": "kaliningrad",
    "lemberg": "lviv",
    # Countries/Regions
    "prussia": "germany",
    "bohemia": "czech republic",
    "moravia": "czech republic",
    "austro-hungary": "austria",
    "yugoslavia": "serbia",
    "czechoslovakia": "czech republic",
    "ussr": "russia",
    "soviet union": "russia",
    "rhodesia": "zimbabwe",
    "burma": "myanmar",
    "ceylon": "sri lanka",
    "persia": "iran",
    "siam": "thailand",
    "formosa": "taiwan",
    "east germany": "germany",
    "west germany": "germany",
}

# Build reverse mapping for bidirectional search
HISTORICAL_MAPPINGS: dict[str, list[str]] = {}
for old_name, new_name in HISTORICAL_NAMES.items():
    # old -> new
    if old_name not in HISTORICAL_MAPPINGS:
        HISTORICAL_MAPPINGS[old_name] = []
    HISTORICAL_MAPPINGS[old_name].append(new_name)
    # new -> old (for reverse lookup)
    if new_name not in HISTORICAL_MAPPINGS:
        HISTORICAL_MAPPINGS[new_name] = []
    HISTORICAL_MAPPINGS[new_name].append(old_name)


def normalize_place_string(place: str) -> str:
    """Normalize a place string for matching.

    Applies lowercasing, abbreviation expansion, and whitespace cleanup.
    """
    result = place.lower().strip()

    # Expand abbreviations
    for abbr, full in PLACE_ABBREVIATIONS.items():
        result = result.replace(abbr, full)

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


# Lazy-loaded geonamescache instance
_gc: geonamescache.GeonamesCache | None = None


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
    gc = _get_geonames_cache()
    components = parse_place_components(place_normalized)

    if not components:
        return None

    # Try to find city (first component)
    city_name = components[0].lower()
    cities = gc.get_cities()

    # Try exact city match
    for city in cities.values():
        if city["name"].lower() == city_name:
            return (city["latitude"], city["longitude"])

    # Try country match (last component)
    if len(components) >= 1:
        country_name = components[-1].lower()
        countries = gc.get_countries()
        country_by_name = gc.get_countries_by_names()

        # Try by country name
        if country_name in country_by_name:
            iso = country_by_name[country_name]
            if iso in countries:
                # Return approximate center (not available directly, use first major city)
                return None  # Skip country-level geocoding for now

    return None


def parse_citation(cite_record) -> Citation | None:
    """Parse a citation (SOUR reference) from an event record."""
    try:
        source_id = normalize_id(cite_record.value)
        if not source_id:
            return None

        page = None
        text = None
        url = None

        # Get page reference
        page_sub = cite_record.sub_tag("PAGE")
        if page_sub and page_sub.value:
            page = str(page_sub.value)

        # Get text/URL from DATA sub-record
        data_sub = cite_record.sub_tag("DATA")
        if data_sub:
            text_sub = data_sub.sub_tag("TEXT")
            if text_sub and text_sub.value:
                text = str(text_sub.value)
            url_sub = data_sub.sub_tag("WWW")
            if url_sub and url_sub.value:
                url = str(url_sub.value)

        # Look up source title from global sources index (may not be populated yet)
        source_title = None

        return Citation(
            source_id=source_id,
            source_title=source_title,
            page=page,
            text=text,
            url=url,
        )
    except (AttributeError, KeyError):
        return None


def parse_event(event_record) -> Event:
    """Parse an event record into an Event dataclass."""
    event_type = event_record.tag
    date_val = None
    place_val = None
    description = None
    citations = []
    notes = []

    try:
        # Get date
        date_sub = event_record.sub_tag("DATE")
        if date_sub and date_sub.value:
            date_val = str(date_sub.value)

        # Get place
        place_sub = event_record.sub_tag("PLAC")
        if place_sub and place_sub.value:
            place_val = str(place_sub.value)

        # Get description (for EVEN type records)
        if event_type == "EVEN":
            type_sub = event_record.sub_tag("TYPE")
            if type_sub and type_sub.value:
                description = str(type_sub.value)

        # Parse citations (SOUR references)
        for sub in event_record.sub_records:
            if sub.tag == "SOUR":
                citation = parse_citation(sub)
                if citation:
                    citations.append(citation)
            elif sub.tag == "NOTE" and sub.value:
                notes.append(str(sub.value))

    except (AttributeError, KeyError):
        pass

    return Event(
        type=event_type,
        date=date_val,
        place=place_val,
        description=description,
        citations=citations,
        notes=notes,
    )


def parse_events_from_record(record) -> list[Event]:
    """Parse all events from an individual or family record."""
    events = []
    try:
        for sub in record.sub_records:
            if sub.tag in EVENT_TAGS:
                event = parse_event(sub)
                events.append(event)
    except (AttributeError, KeyError):
        pass
    return events


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
    global \
        individuals, \
        families, \
        sources, \
        repositories, \
        surname_index, \
        birth_year_index, \
        place_index
    global places, individual_places

    if not GEDCOM_FILE.exists():
        raise FileNotFoundError(f"GEDCOM file not found: {GEDCOM_FILE}")

    with GedcomReader(str(GEDCOM_FILE)) as reader:
        # Parse repositories (level-0 REPO records)
        for record in reader.records0("REPO"):
            repo_id = record.xref_id
            name = get_record_value(record, "NAME")
            address = None
            url = None

            # Get address and URL
            for sub in record.sub_records:
                if sub.tag == "ADDR" and sub.value:
                    address = str(sub.value)
                elif sub.tag == "WWW" and sub.value:
                    url = str(sub.value)

            repo = Repository(
                id=repo_id,  # type: ignore[arg-type]
                name=name,
                address=address,
                url=url,
            )
            repositories[repo_id] = repo  # type: ignore[index]

        # Parse sources (level-0 SOUR records)
        for record in reader.records0("SOUR"):
            source_id = record.xref_id
            title = get_record_value(record, "TITL")
            author = get_record_value(record, "AUTH")
            publication = get_record_value(record, "PUBL")
            repo_id = None
            note = None

            # Get repository reference and note
            for sub in record.sub_records:
                if sub.tag == "REPO" and sub.value:
                    repo_id = normalize_id(sub.value)
                elif sub.tag == "NOTE" and sub.value:
                    note = str(sub.value)

            source = Source(
                id=source_id,  # type: ignore[arg-type]
                title=title,
                author=author,
                publication=publication,
                repository_id=repo_id,
                note=note,
            )
            sources[source_id] = source  # type: ignore[index]

        # Parse individuals
        for record in reader.records0("INDI"):
            indi_id = record.xref_id
            given, surname = parse_name(record)
            sex = get_record_value(record, "SEX")
            birth_date, birth_place = get_event_details(record, "BIRT")
            death_date, death_place = get_event_details(record, "DEAT")

            # Parse all events with citations and notes
            events = parse_events_from_record(record)

            # Get family references and individual-level notes
            famc = None
            fams_list = []
            indi_notes = []
            for sub in record.sub_records:
                if sub.tag == "FAMC" and sub.value:
                    famc = normalize_id(sub.value)
                elif sub.tag == "FAMS" and sub.value:
                    fams_list.append(normalize_id(sub.value))
                elif sub.tag == "NOTE" and sub.value:
                    # Individual-level note (level 1) - biographical content
                    indi_notes.append(str(sub.value))

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
                events=events,
                notes=indi_notes,
            )
            individuals[indi_id] = indi  # type: ignore[index]

            # Build indexes
            if surname:
                surname_index[surname.lower()].append(indi_id)  # type: ignore[arg-type]

            birth_year = extract_year(birth_date)
            if birth_year:
                birth_year_index[birth_year].append(indi_id)  # type: ignore[arg-type]

            # Index all places (from birth/death and all events)
            all_places = [birth_place, death_place]
            for event in events:
                if event.place:
                    all_places.append(event.place)

            for place_str in all_places:
                if place_str:
                    place_lower = place_str.lower()
                    place_index[place_lower].append(indi_id)  # type: ignore[arg-type]

                    # Build Place object and add to places index
                    place_id = get_place_id(place_str)
                    if place_id not in places:
                        places[place_id] = create_place(place_str)
                    individual_places[indi_id].append(place_id)  # type: ignore[index]

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

            # Index marriage place
            if marr_place:
                place_id = get_place_id(marr_place)
                if place_id not in places:
                    places[place_id] = create_place(marr_place)

    # Second pass: populate source titles in citations
    for indi in individuals.values():
        for event in indi.events:
            for citation in event.citations:
                if citation.source_id and citation.source_id in sources:
                    citation.source_title = sources[citation.source_id].title

    # Third pass: geocode places (lazily - only on first spatial query)
    # This is done lazily to avoid slowing down startup


def geocode_all_places():
    """Geocode all places that don't have coordinates yet.

    Called lazily on first spatial query.
    """
    for place in places.values():
        if place.latitude is None:
            coords = geocode_place_coords(place.normalized)
            if coords:
                place.latitude, place.longitude = coords


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


# ============== FUZZY PLACE SEARCH FUNCTIONS ==============


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
    unique_places = [p.original for p in places.values()]

    if not unique_places:
        return []

    # Also normalize the choices for better matching
    choices_normalized = {p.original: p.normalized for p in places.values()}

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

    for place in places.values():
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
    for indexed_place in place_index:
        if place_lower in indexed_place:
            place_scores[indexed_place] = 100.0

    # Strategy 2: Normalized match
    place_normalized = normalize_place_string(place)
    for p in places.values():
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
        for indexed_place in place_index:
            if variant_lower in indexed_place and indexed_place not in place_scores:
                place_scores[indexed_place] = 80.0  # Historical match score

    # Collect individuals from matching places
    for matching_place, score in sorted(place_scores.items(), key=lambda x: -x[1]):
        if matching_place in place_index:
            for indi_id in place_index[matching_place]:
                if indi_id not in seen_individuals and indi_id in individuals:
                    seen_individuals.add(indi_id)
                    indi = individuals[indi_id]
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

    for p in places.values():
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
    for place in places.values():
        results.append(place.to_summary())
        if len(results) >= max_results:
            break
    return results


def _get_place(place_id: str) -> dict | None:
    """Get a place by its ID."""
    place = places.get(place_id)
    if place:
        return place.to_dict()
    return None


def _geocode_place(place: str) -> dict | None:
    """Get coordinates for a place name.

    Returns dict with latitude, longitude, and source of geocoding.
    """
    # First check if we already have this place geocoded
    place_id = get_place_id(place)
    if place_id in places:
        p = places[place_id]
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
        if place_id in places:
            places[place_id].latitude = coords[0]
            places[place_id].longitude = coords[1]
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
        if place_id in places:
            p = places[place_id]
            if p.latitude is not None and p.longitude is not None:
                ref_coords = (p.latitude, p.longitude)

    if not ref_coords:
        return []

    results = []
    seen_individuals: set[str] = set()

    for place_id, p in places.items():
        if p.latitude is None or p.longitude is None:
            continue

        dist = haversine(ref_coords, (p.latitude, p.longitude), unit=Unit.KILOMETERS)
        if dist <= radius_km:
            # Find individuals at this place
            for indi_id, indi_place_ids in individual_places.items():
                if place_id not in indi_place_ids:
                    continue
                if indi_id in seen_individuals:
                    continue
                indi = individuals.get(indi_id)
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


# ============== SOURCE FUNCTIONS ==============


def _get_sources(max_results: int = 100) -> list[dict]:
    """Get all sources in the tree."""
    results = []
    for source in sources.values():
        results.append(source.to_summary())
        if len(results) >= max_results:
            break
    return results


def _get_source(source_id: str) -> dict | None:
    """Get a source by its ID."""
    lookup_id = _normalize_lookup_id(source_id)
    source = sources.get(lookup_id)
    return source.to_dict() if source else None


def _search_sources(query: str, max_results: int = 50) -> list[dict]:
    """Search sources by title or author."""
    query_lower = query.lower()
    results = []

    for source in sources.values():
        title_match = source.title and query_lower in source.title.lower()
        author_match = source.author and query_lower in source.author.lower()

        if title_match or author_match:
            results.append(source.to_summary())
            if len(results) >= max_results:
                break

    return results


# ============== EVENT FUNCTIONS ==============


def _get_events(individual_id: str) -> list[dict]:
    """Get all events for an individual."""
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
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

    for indi in individuals.values():
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
    indi = individuals.get(lookup_id)
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
    indi = individuals.get(lookup_id)
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
    indi = individuals.get(lookup_id)
    if not indi:
        return []

    # Sort events by date (events without dates come last)
    def sort_key(event: Event) -> tuple[int, str]:
        year = extract_year(event.date)
        # Put events without years at the end, sort by year then by date string
        return (year if year else 9999, event.date or "")

    sorted_events = sorted(indi.events, key=sort_key)
    return [event.to_dict() for event in sorted_events]


# ============== NARRATIVE FUNCTIONS ==============


def _get_biography(individual_id: str) -> dict | None:
    """Get a comprehensive narrative package for one person.

    Returns everything needed to understand a person's life in ONE call:
    - Vital summary
    - Birth/death facts
    - Family context with names (not IDs)
    - All events with full citation details including URLs
    - All biographical notes
    """
    lookup_id = _normalize_lookup_id(individual_id)
    indi = individuals.get(lookup_id)
    if not indi:
        return None

    # Build vital summary
    vital_parts = []
    if indi.birth_date or indi.birth_place:
        birth_info = "Born"
        if indi.birth_date:
            birth_info += f" {indi.birth_date}"
        if indi.birth_place:
            birth_info += f" in {indi.birth_place}"
        vital_parts.append(birth_info)
    if indi.death_date or indi.death_place:
        death_info = "Died"
        if indi.death_date:
            death_info += f" {indi.death_date}"
        if indi.death_place:
            death_info += f" in {indi.death_place}"
        vital_parts.append(death_info)
    vital_summary = ". ".join(vital_parts) + "." if vital_parts else ""

    # Get parents' names
    parents = []
    if indi.family_as_child:
        fam = families.get(indi.family_as_child)
        if fam:
            if fam.husband_id and fam.husband_id in individuals:
                parents.append(individuals[fam.husband_id].full_name())
            if fam.wife_id and fam.wife_id in individuals:
                parents.append(individuals[fam.wife_id].full_name())

    # Get spouses with marriage info
    spouses_info = []
    for fam_id in indi.families_as_spouse:
        fam = families.get(fam_id)
        if fam:
            spouse_id = fam.wife_id if fam.husband_id == lookup_id else fam.husband_id
            if spouse_id and spouse_id in individuals:
                spouse_data = {"name": individuals[spouse_id].full_name()}
                if fam.marriage_date:
                    spouse_data["marriage_date"] = fam.marriage_date
                if fam.marriage_place:
                    spouse_data["marriage_place"] = fam.marriage_place
                spouses_info.append(spouse_data)

    # Get children's names
    children_names = []
    seen_children = set()
    for fam_id in indi.families_as_spouse:
        fam = families.get(fam_id)
        if fam:
            for child_id in fam.children_ids:
                if child_id not in seen_children and child_id in individuals:
                    seen_children.add(child_id)
                    children_names.append(individuals[child_id].full_name())

    # Build events with full citation details
    events_data: list[dict] = []
    for event in indi.events:
        event_dict: dict = {
            "type": event.type,
            "date": event.date,
            "place": event.place,
        }
        if event.description:
            event_dict["description"] = event.description
        if event.notes:
            event_dict["notes"] = event.notes

        # Include citations with full details
        citations_data: list[dict] = []
        for citation in event.citations:
            cite_data: dict = {
                "source": citation.source_title or citation.source_id,
            }
            if citation.page:
                cite_data["page"] = citation.page
            if citation.text:
                cite_data["text"] = citation.text
            if citation.url:
                cite_data["url"] = citation.url
            citations_data.append(cite_data)
        if citations_data:
            event_dict["citations"] = citations_data

        events_data.append(event_dict)

    return {
        "id": indi.id,
        "name": indi.full_name(),
        "vital_summary": vital_summary,
        "birth": {"date": indi.birth_date, "place": indi.birth_place},
        "death": {"date": indi.death_date, "place": indi.death_place},
        "sex": indi.sex,
        "parents": parents,
        "spouses": spouses_info,
        "children": children_names,
        "events": events_data,
        "notes": indi.notes,
    }


def _search_narrative(query: str, max_results: int = 50) -> dict:
    """Full-text search across all narrative content.

    Searches:
    - Individual-level notes (obituaries, stories, directory entries)
    - Event-level notes
    - Citation text fields
    - Source titles
    """
    query_lower = query.lower()
    results: list[dict] = []

    for indi in individuals.values():
        if len(results) >= max_results:
            break

        # Search individual-level notes
        for note in indi.notes:
            if query_lower in note.lower():
                # Create snippet with context
                snippet = _create_snippet(note, query_lower)
                results.append(
                    {
                        "individual_id": indi.id,
                        "individual_name": indi.full_name(),
                        "source": "note",
                        "snippet": snippet,
                        "full_text": note,
                    }
                )
                if len(results) >= max_results:
                    break

        if len(results) >= max_results:
            break

        # Search event notes and citation text
        for event in indi.events:
            if len(results) >= max_results:
                break

            # Event notes
            for note in event.notes:
                if query_lower in note.lower():
                    snippet = _create_snippet(note, query_lower)
                    results.append(
                        {
                            "individual_id": indi.id,
                            "individual_name": indi.full_name(),
                            "source": "event_note",
                            "event_type": event.type,
                            "event_date": event.date,
                            "snippet": snippet,
                            "full_text": note,
                        }
                    )
                    if len(results) >= max_results:
                        break

            if len(results) >= max_results:
                break

            # Citation text
            for citation in event.citations:
                if citation.text and query_lower in citation.text.lower():
                    snippet = _create_snippet(citation.text, query_lower)
                    results.append(
                        {
                            "individual_id": indi.id,
                            "individual_name": indi.full_name(),
                            "source": "citation_text",
                            "event_type": event.type,
                            "source_title": citation.source_title,
                            "snippet": snippet,
                            "full_text": citation.text,
                        }
                    )
                    if len(results) >= max_results:
                        break

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }


def _create_snippet(text: str, query: str, context_chars: int = 50) -> str:
    """Create a snippet with the query highlighted and surrounded by context."""
    text_lower = text.lower()
    pos = text_lower.find(query)
    if pos == -1:
        return text[:100] + "..." if len(text) > 100 else text

    start = max(0, pos - context_chars)
    end = min(len(text), pos + len(query) + context_chars)

    snippet = ""
    if start > 0:
        snippet += "..."
    # Keep original case but mark the match
    before = text[start:pos]
    match = text[pos : pos + len(query)]
    after = text[pos + len(query) : end]
    snippet += f"{before}**{match}**{after}"
    if end < len(text):
        snippet += "..."

    return snippet


def _get_repositories() -> list[dict]:
    """Get all repositories in the tree."""
    return [repo.to_dict() for repo in repositories.values()]


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


# ============== FUZZY PLACE SEARCH TOOLS ==============


@mcp.tool()
def fuzzy_search_place(place: str, threshold: int = 70, max_results: int = 50) -> list[dict]:
    """
    Search for individuals by place with fuzzy matching.

    Handles typos, abbreviations, spelling variations, and historical name changes.
    Uses multiple matching strategies:
    - Exact substring matching
    - Abbreviation expansion (St. -> Saint, N.Y. -> New York)
    - Fuzzy string matching (typo tolerance)
    - Phonetic matching (similar pronunciation)
    - Historical name variants (Constantinople -> Istanbul)

    Args:
        place: Place name to search (tolerates typos and variations)
        threshold: Minimum similarity score 0-100 (default 70)
        max_results: Maximum results to return

    Returns:
        List of individuals with match info including score
    """
    return _fuzzy_search_place(place, threshold, max_results)


@mcp.tool()
def search_similar_places(place: str, max_results: int = 20) -> list[dict]:
    """
    Find places in the tree similar to the given name.

    Useful for discovering spelling variations, typos, or related locations.
    Combines fuzzy string matching and phonetic analysis.

    Args:
        place: Place name to find similar matches for
        max_results: Maximum results to return

    Returns:
        List of similar places with similarity scores and match type
    """
    return _search_similar_places(place, max_results)


@mcp.tool()
def get_place_variants(place: str) -> list[dict]:
    """
    Get all variant spellings/forms of a place found in the tree.

    Groups places that normalize to the same form or match phonetically.
    Example: "New York" might return ["New York", "N.Y.", "NYC", "New York City"]

    Args:
        place: Place name to find variants for

    Returns:
        List of variant places with match type (normalized, phonetic, or fuzzy)
    """
    return _get_place_variants(place)


@mcp.tool()
def get_all_places(max_results: int = 500) -> list[dict]:
    """
    Get all unique places in the genealogy tree.

    Returns:
        List of place summaries (id, original, normalized)
    """
    return _get_all_places(max_results)


@mcp.tool()
def get_place(place_id: str) -> dict | None:
    """
    Get a place by its ID.

    Args:
        place_id: The place ID (hash of normalized form)

    Returns:
        Full place record with components and coordinates, or None
    """
    return _get_place(place_id)


@mcp.tool()
def geocode_place(place: str) -> dict | None:
    """
    Get geographic coordinates for a place name.

    Uses offline GeoNames data for geocoding.

    Args:
        place: Place name to geocode

    Returns:
        Dict with latitude, longitude, and source, or None if not found
    """
    return _geocode_place(place)


@mcp.tool()
def search_nearby(
    place: str,
    radius_km: float = 50,
    event_types: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """
    Find individuals with events within a radius of a place.

    Performs spatial search using geographic coordinates.
    Note: Only places that can be geocoded will be included.

    Args:
        place: Reference place name (will be geocoded)
        radius_km: Search radius in kilometers (default 50)
        event_types: Filter by event types (BIRT, DEAT, RESI, etc.)
        max_results: Maximum results to return

    Returns:
        List of individuals with distance info, sorted by distance
    """
    return _search_nearby(place, radius_km, event_types, max_results)


@mcp.tool()
def get_statistics() -> dict:
    """
    Get statistics about the genealogy tree.

    Returns:
        Dictionary with counts, date ranges, and other statistics
    """
    return _get_statistics()


# ============== SOURCE TOOLS ==============


@mcp.tool()
def get_sources(max_results: int = 100) -> list[dict]:
    """
    Get all sources in the genealogy tree.

    Args:
        max_results: Maximum number of sources to return (default 100)

    Returns:
        List of source summaries (id, title, author)
    """
    return _get_sources(max_results)


@mcp.tool()
def get_source(source_id: str) -> dict | None:
    """
    Get full details for a source by its GEDCOM ID.

    Args:
        source_id: The GEDCOM source ID (e.g., "S123" or "@S123@")

    Returns:
        Full source record or None if not found
    """
    return _get_source(source_id)


@mcp.tool()
def search_sources(query: str, max_results: int = 50) -> list[dict]:
    """
    Search sources by title or author.

    Args:
        query: Search term (case-insensitive partial match)
        max_results: Maximum number of results (default 50)

    Returns:
        List of matching source summaries
    """
    return _search_sources(query, max_results)


# ============== EVENT TOOLS ==============


@mcp.tool()
def get_events(individual_id: str) -> list[dict]:
    """
    Get all life events for an individual.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of events (birth, death, residence, occupation, etc.)
    """
    return _get_events(individual_id)


@mcp.tool()
def search_events(
    event_type: str | None = None,
    place: str | None = None,
    year: int | None = None,
    year_range: int = 5,
    max_results: int = 50,
) -> list[dict]:
    """
    Search events by type, place, and/or year.

    Args:
        event_type: Event type to filter by (BIRT, DEAT, RESI, OCCU, etc.)
        place: Place name to search for (partial match)
        year: Year to search for
        year_range: Years around the given year to include (default 5)
        max_results: Maximum number of results (default 50)

    Returns:
        List of matching events with individual info
    """
    return _search_events(event_type, place, year, year_range, max_results)


@mcp.tool()
def get_citations(individual_id: str) -> list[dict]:
    """
    Get all source citations for an individual across all events.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of citations with source and event context
    """
    return _get_citations(individual_id)


@mcp.tool()
def get_notes(individual_id: str) -> list[dict]:
    """
    Get all notes for an individual across all events.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of notes with event context
    """
    return _get_notes(individual_id)


@mcp.tool()
def get_timeline(individual_id: str) -> list[dict]:
    """
    Get chronological timeline of events for an individual.

    Args:
        individual_id: The GEDCOM ID of the individual

    Returns:
        List of events sorted by date (earliest first)
    """
    return _get_timeline(individual_id)


# ============== NARRATIVE TOOLS ==============


@mcp.tool()
def get_biography(individual_id: str) -> dict | None:
    """
    Get a comprehensive narrative package for one person.

    This is the ideal tool for building a complete understanding of someone's life
    in ONE call. Returns everything needed for biographical narrative:

    - vital_summary: Quick "Born X. Died Y." summary
    - birth/death: Full date and place info
    - parents/spouses/children: Family names (not IDs) for easy narrative use
    - events: All life events with full citation details including URLs
    - notes: All biographical notes (obituaries, baptism records, directory entries, etc.)

    Args:
        individual_id: The GEDCOM ID of the individual (e.g., "I123" or "@I123@")

    Returns:
        Complete biography dict or None if not found
    """
    return _get_biography(individual_id)


@mcp.tool()
def search_narrative(query: str, max_results: int = 50) -> dict:
    """
    Full-text search across all narrative content in the tree.

    Searches:
    - Individual-level notes (obituaries, stories, census extracts, directory entries)
    - Event-level notes
    - Citation text fields

    Perfect for queries like:
    - "Find all obituaries" -> search_narrative("obituary")
    - "Who worked at the steel mill?" -> search_narrative("steel mill")
    - "Find baptism records" -> search_narrative("baptism")

    Args:
        query: Text to search for (case-insensitive)
        max_results: Maximum results to return (default 50)

    Returns:
        Dict with query, result_count, and list of matches with snippets
    """
    return _search_narrative(query, max_results)


@mcp.tool()
def get_repositories() -> list[dict]:
    """
    Get all source repositories in the tree.

    Repositories are where sources come from (e.g., Ancestry.com, Family History Library).

    Returns:
        List of repository records with id, name, address, and url
    """
    return _get_repositories()


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


@mcp.resource("gedcom://source/{id}")
def resource_source(id: str) -> str:
    """Get source record by ID."""
    source = _get_source(id)
    if source:
        return str(source)
    return f"Source {id} not found"


@mcp.resource("gedcom://sources")
def resource_sources() -> str:
    """Get list of all sources."""
    source_list = _get_sources(max_results=1000)
    lines = []
    for s in source_list:
        title = s.get("title") or "Untitled"
        author = s.get("author") or "Unknown author"
        lines.append(f"{s['id']}: {title} by {author}")
    return "\n".join(lines)


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
