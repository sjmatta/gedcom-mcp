"""Shared fixtures for GEDCOM server tests."""

import os
from pathlib import Path

import pytest

# Set GEDCOM env vars BEFORE importing any gedcom_server modules
# This is critical because modules are imported at collection time
# Set explicit test values so .env doesn't override them (load_dotenv won't override existing)
_TEST_GEDCOM = Path(__file__).parent / "fixtures" / "sample.ged"
os.environ["GEDCOM_FILE"] = str(_TEST_GEDCOM)
os.environ["GEDCOM_HOME_PERSON_ID"] = ""  # Empty string = auto-detect in sample.ged

# Now import and initialize gedcom_server (safe because env var is set)
from gedcom_server import initialize  # noqa: E402

initialize()

from gedcom_server.core import _get_home_person  # noqa: E402
from gedcom_server.state import HOME_PERSON_ID, families, individuals  # noqa: E402


@pytest.fixture
def home_person_id():
    """The home person's GEDCOM ID."""
    return HOME_PERSON_ID


@pytest.fixture
def home_person():
    """The home person's full record."""
    return _get_home_person()


@pytest.fixture
def sample_individual_id():
    """Any valid individual ID from the loaded data."""
    return next(iter(individuals.keys()))


@pytest.fixture
def sample_family_id():
    """Any valid family ID from the loaded data."""
    return next(iter(families.keys()))


@pytest.fixture
def individual_with_parents():
    """An individual who has parents in the tree."""
    for indi in individuals.values():
        if indi.family_as_child and indi.family_as_child in families:
            return indi
    pytest.skip("No individual with parents found")


@pytest.fixture
def individual_with_children():
    """An individual who has children in the tree."""
    for indi in individuals.values():
        if indi.families_as_spouse:
            for fam_id in indi.families_as_spouse:
                fam = families.get(fam_id)
                if fam and fam.children_ids:
                    return indi
    pytest.skip("No individual with children found")


@pytest.fixture
def individual_with_spouse():
    """An individual who has a spouse in the tree."""
    for indi in individuals.values():
        if indi.families_as_spouse:
            for fam_id in indi.families_as_spouse:
                fam = families.get(fam_id)
                if fam:
                    spouse_id = fam.wife_id if fam.husband_id == indi.id else fam.husband_id
                    if spouse_id and spouse_id in individuals:
                        return indi
    pytest.skip("No individual with spouse found")


@pytest.fixture
def family_with_multiple_children():
    """A family with more than one child."""
    for fam in families.values():
        if len(fam.children_ids) > 1:
            return fam
    pytest.skip("No family with multiple children found")


@pytest.fixture
def sample_source_id():
    """Any valid source ID from the loaded data."""
    from gedcom_server.state import sources

    if sources:
        return next(iter(sources.keys()))
    pytest.skip("No sources found")


@pytest.fixture
def individual_with_events():
    """An individual who has events in the tree."""
    for indi in individuals.values():
        if indi.events:
            return indi
    pytest.skip("No individual with events found")


@pytest.fixture
def individual_with_citations():
    """An individual who has citations on their events."""
    for indi in individuals.values():
        for event in indi.events:
            if event.citations:
                return indi
    pytest.skip("No individual with citations found")


@pytest.fixture
def individual_with_notes():
    """An individual who has notes on their events."""
    for indi in individuals.values():
        for event in indi.events:
            if event.notes:
                return indi
    pytest.skip("No individual with notes found")
