"""Global mutable state for GEDCOM data storage."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from .models import Family, Individual, Place, Repository, Source

# Configuration (set by configure() at startup)
GEDCOM_FILE: Path | None = None
HOME_PERSON_ID: str | None = None

# Global indexes (populated at startup by load_gedcom)
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

# Note: Semantic search state is managed in semantic.py module
# (embeddings, embedding_ids, embedding_texts)


def _resolve_gedcom_path() -> Path:
    """Get GEDCOM path from GEDCOM_FILE env var.

    Raises:
        FileNotFoundError: If GEDCOM_FILE env var not set or file doesn't exist.
    """
    env_path = os.getenv("GEDCOM_FILE")
    if not env_path:
        raise FileNotFoundError(
            "GEDCOM_FILE environment variable not set.\n"
            "Set it to the path of your .ged file:\n"
            "  export GEDCOM_FILE=/path/to/your/tree.ged\n"
            "Or use the --gedcom-file CLI argument:\n"
            "  gedcom-server --gedcom-file /path/to/your/tree.ged"
        )
    path = Path(env_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"GEDCOM file not found: {path}")
    return path


def _detect_home_person() -> str | None:
    """Auto-detect home person as individual with most family connections.

    Scores each person by: descendants + ancestors + spouse connections.
    Returns the highest-scoring individual's ID.
    """
    if not individuals:
        return None

    def score_individual(indi_id: str) -> int:
        """Calculate connection score for an individual."""
        score = 0
        indi = individuals.get(indi_id)
        if not indi:
            return 0

        # Score for being in a family as a child (has parents)
        if indi.family_as_child and indi.family_as_child in families:
            score += 2
            parent_family = families[indi.family_as_child]
            # Score for having grandparents
            for parent_id in [parent_family.husband_id, parent_family.wife_id]:
                if parent_id:
                    parent = individuals.get(parent_id)
                    if parent and parent.family_as_child:
                        score += 1

        # Score for being in families as spouse (has spouse/children)
        for fam_id in indi.families_as_spouse or []:
            fam = families.get(fam_id)
            if fam:
                # Score for having a spouse
                spouse_id = fam.wife_id if fam.husband_id == indi_id else fam.husband_id
                if spouse_id and spouse_id in individuals:
                    score += 1
                # Score for each child
                score += len(fam.children_ids or [])

        return score

    # Find the individual with the highest score
    best_id = None
    best_score = -1
    for indi_id in individuals:
        score = score_individual(indi_id)
        if score > best_score:
            best_score = score
            best_id = indi_id

    return best_id


def configure() -> None:
    """Initialize configuration from environment. Called at startup.

    Loads .env file if present, then reads GEDCOM_FILE from environment.
    Note: load_dotenv() does NOT override existing env vars by default.
    """
    global GEDCOM_FILE
    load_dotenv()  # Load .env, won't override existing env vars
    GEDCOM_FILE = _resolve_gedcom_path()
