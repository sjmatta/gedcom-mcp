"""Shared fixtures for GEDCOM server tests."""

import pytest

import gedcom_server as gs


@pytest.fixture
def home_person_id():
    """The home person's GEDCOM ID."""
    return gs.HOME_PERSON_ID


@pytest.fixture
def home_person():
    """The home person's full record."""
    return gs._get_home_person()


@pytest.fixture
def sample_individual_id():
    """Any valid individual ID from the loaded data."""
    return next(iter(gs.individuals.keys()))


@pytest.fixture
def sample_family_id():
    """Any valid family ID from the loaded data."""
    return next(iter(gs.families.keys()))


@pytest.fixture
def individual_with_parents():
    """An individual who has parents in the tree."""
    for indi in gs.individuals.values():
        if indi.family_as_child and indi.family_as_child in gs.families:
            return indi
    pytest.skip("No individual with parents found")


@pytest.fixture
def individual_with_children():
    """An individual who has children in the tree."""
    for indi in gs.individuals.values():
        if indi.families_as_spouse:
            for fam_id in indi.families_as_spouse:
                fam = gs.families.get(fam_id)
                if fam and fam.children_ids:
                    return indi
    pytest.skip("No individual with children found")


@pytest.fixture
def individual_with_spouse():
    """An individual who has a spouse in the tree."""
    for indi in gs.individuals.values():
        if indi.families_as_spouse:
            for fam_id in indi.families_as_spouse:
                fam = gs.families.get(fam_id)
                if fam:
                    spouse_id = fam.wife_id if fam.husband_id == indi.id else fam.husband_id
                    if spouse_id and spouse_id in gs.individuals:
                        return indi
    pytest.skip("No individual with spouse found")


@pytest.fixture
def family_with_multiple_children():
    """A family with more than one child."""
    for fam in gs.families.values():
        if len(fam.children_ids) > 1:
            return fam
    pytest.skip("No family with multiple children found")


@pytest.fixture
def sample_source_id():
    """Any valid source ID from the loaded data."""
    if gs.sources:
        return next(iter(gs.sources.keys()))
    pytest.skip("No sources found")


@pytest.fixture
def individual_with_events():
    """An individual who has events in the tree."""
    for indi in gs.individuals.values():
        if indi.events:
            return indi
    pytest.skip("No individual with events found")


@pytest.fixture
def individual_with_citations():
    """An individual who has citations on their events."""
    for indi in gs.individuals.values():
        for event in indi.events:
            if event.citations:
                return indi
    pytest.skip("No individual with citations found")


@pytest.fixture
def individual_with_notes():
    """An individual who has notes on their events."""
    for indi in gs.individuals.values():
        for event in indi.events:
            if event.notes:
                return indi
    pytest.skip("No individual with notes found")
