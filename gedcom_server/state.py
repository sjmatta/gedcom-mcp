"""Global mutable state for GEDCOM data storage."""

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Family, Individual, Place, Repository, Source

# Configuration
GEDCOM_FILE = Path(__file__).parent.parent / "tree.ged"
HOME_PERSON_ID = "@I370014870784@"  # Stephen John MATTA (1984)

# Global indexes (populated at startup by load_gedcom)
individuals: dict[str, "Individual"] = {}
families: dict[str, "Family"] = {}
sources: dict[str, "Source"] = {}
repositories: dict[str, "Repository"] = {}
surname_index: dict[str, list[str]] = defaultdict(list)
birth_year_index: dict[int, list[str]] = defaultdict(list)
place_index: dict[str, list[str]] = defaultdict(list)  # place (lowercase) -> individual IDs

# Place indexes for fuzzy search and geocoding
places: dict[str, "Place"] = {}  # place_id -> Place
individual_places: dict[str, list[str]] = defaultdict(list)  # individual_id -> list of place_ids
