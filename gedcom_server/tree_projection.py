"""Build detached read indexes independently of the editing backend."""

import os
import tempfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from .parsing import load_gedcom

INDEXES = (
    "individuals",
    "families",
    "sources",
    "repositories",
    "surname_index",
    "birth_year_index",
    "place_index",
    "places",
    "individual_places",
)


def projection(data: bytes, directory: Path):
    """Parse into detached indexes without disturbing readers or derived workers."""
    fd, name = tempfile.mkstemp(suffix=".ged", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        target = SimpleNamespace(GEDCOM_FILE=Path(name), HOME_PERSON_ID=None)
        for key in INDEXES:
            setattr(
                target,
                key,
                defaultdict(list) if key.endswith("index") or key == "individual_places" else {},
            )
        load_gedcom(target, derived=False)
        return target
    finally:
        os.unlink(name)
