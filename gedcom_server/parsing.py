"""GEDCOM file parsing functions."""

import os

from ged4py import GedcomReader

from . import state
from .constants import EVENT_TAGS
from .helpers import (
    create_place,
    extract_year,
    geocode_place_coords,
    get_event_details,
    get_place_id,
    get_record_value,
    normalize_id,
)
from .models import Citation, Event, Family, Individual, Repository, Source


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
    """Parse the GEDCOM file and build indexes.

    Requires configure() to be called first to set state.GEDCOM_FILE.
    """
    if state.GEDCOM_FILE is None:
        raise RuntimeError("configure() must be called before load_gedcom()")
    if not state.GEDCOM_FILE.exists():
        raise FileNotFoundError(f"GEDCOM file not found: {state.GEDCOM_FILE}")

    with GedcomReader(str(state.GEDCOM_FILE)) as reader:
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
            state.repositories[repo_id] = repo  # type: ignore[index]

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
            state.sources[source_id] = source  # type: ignore[index]

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
            state.individuals[indi_id] = indi  # type: ignore[index]

            # Build indexes
            if surname:
                state.surname_index[surname.lower()].append(indi_id)  # type: ignore[arg-type]

            birth_year = extract_year(birth_date)
            if birth_year:
                state.birth_year_index[birth_year].append(indi_id)  # type: ignore[arg-type]

            # Index all places (from birth/death and all events)
            all_places = [birth_place, death_place]
            for event in events:
                if event.place:
                    all_places.append(event.place)

            for place_str in all_places:
                if place_str:
                    place_lower = place_str.lower()
                    state.place_index[place_lower].append(indi_id)  # type: ignore[arg-type]

                    # Build Place object and add to places index
                    place_id = get_place_id(place_str)
                    if place_id not in state.places:
                        state.places[place_id] = create_place(place_str)
                    state.individual_places[indi_id].append(place_id)  # type: ignore[index]

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
            state.families[fam_id] = fam  # type: ignore[index]

            # Index marriage place
            if marr_place:
                place_id = get_place_id(marr_place)
                if place_id not in state.places:
                    state.places[place_id] = create_place(marr_place)

    # Second pass: populate source titles in citations
    for indi in state.individuals.values():
        for event in indi.events:
            for citation in event.citations:
                if citation.source_id and citation.source_id in state.sources:
                    citation.source_title = state.sources[citation.source_id].title

    # Third pass: geocode places (lazily - only on first spatial query)
    # This is done lazily to avoid slowing down startup

    # Set home person from env var or auto-detect
    env_home = os.getenv("GEDCOM_HOME_PERSON_ID")
    if env_home:
        state.HOME_PERSON_ID = normalize_id(env_home)
    else:
        state.HOME_PERSON_ID = state._detect_home_person()

    # Build semantic search embeddings (if enabled)
    from .semantic import build_embeddings

    build_embeddings()


def geocode_all_places():
    """Geocode all places that don't have coordinates yet.

    Called lazily on first spatial query.
    """
    for place in state.places.values():
        if place.latitude is None:
            coords = geocode_place_coords(place.normalized)
            if coords:
                place.latitude, place.longitude = coords
