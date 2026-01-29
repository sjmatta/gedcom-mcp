"""Data models for GEDCOM genealogy records."""

from dataclasses import dataclass, field


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
