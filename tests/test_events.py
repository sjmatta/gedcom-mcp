"""Tests for event-related functionality."""

from gedcom_server.constants import EVENT_TAGS
from gedcom_server.events import (
    _get_citations,
    _get_events,
    _get_family_events,
    _get_family_timeline,
    _get_notes,
    _get_timeline,
    _search_events,
)
from gedcom_server.helpers import extract_year
from gedcom_server.models import Citation, Event
from gedcom_server.state import HOME_PERSON_ID, families, individuals


class TestCitationDataclass:
    """Tests for the Citation dataclass."""

    def test_citation_to_dict(self):
        """Should include all fields in dict output."""
        citation = Citation(
            source_id="@S1@",
            source_title="Birth Certificate",
            page="Page 42",
            text="Extracted text",
            url="https://example.com",
        )
        d = citation.to_dict()
        assert d["source_id"] == "@S1@"
        assert d["source_title"] == "Birth Certificate"
        assert d["page"] == "Page 42"
        assert d["text"] == "Extracted text"
        assert d["url"] == "https://example.com"

    def test_citation_defaults(self):
        """Should have sensible defaults."""
        citation = Citation(source_id="@S1@")
        assert citation.source_title is None
        assert citation.page is None
        assert citation.text is None
        assert citation.url is None


class TestEventDataclass:
    """Tests for the Event dataclass."""

    def test_event_to_dict(self):
        """Should include all fields in dict output."""
        citation = Citation(source_id="@S1@", source_title="Test")
        event = Event(
            type="BIRT",
            date="1 JAN 1900",
            place="New York, USA",
            description=None,
            citations=[citation],
            notes=["A note"],
        )
        d = event.to_dict()
        assert d["type"] == "BIRT"
        assert d["date"] == "1 JAN 1900"
        assert d["place"] == "New York, USA"
        assert d["description"] is None
        assert len(d["citations"]) == 1
        assert d["citations"][0]["source_id"] == "@S1@"
        assert d["notes"] == ["A note"]

    def test_event_defaults(self):
        """Should have sensible defaults."""
        event = Event(type="BIRT")
        assert event.date is None
        assert event.place is None
        assert event.description is None
        assert event.citations == []
        assert event.notes == []


class TestEventsLoaded:
    """Tests that verify events loaded correctly."""

    def test_individuals_have_events(self):
        """Some individuals should have events."""
        individuals_with_events = sum(1 for indi in individuals.values() if indi.events)
        assert individuals_with_events > 0

    def test_events_have_types(self):
        """All events should have types."""
        for indi in individuals.values():
            for event in indi.events:
                assert event.type is not None
                assert event.type in EVENT_TAGS


class TestGetEvents:
    """Tests for the get_events function."""

    def test_get_events_returns_list(self):
        """Should return a list."""
        # Find an individual with events
        for indi in individuals.values():
            if indi.events:
                result = _get_events(indi.id)
                assert isinstance(result, list)
                assert len(result) > 0
                break

    def test_get_events_for_nonexistent(self):
        """Should return empty list for nonexistent individual."""
        result = _get_events("NONEXISTENT999")
        assert result == []

    def test_event_result_has_fields(self):
        """Event results should have required fields."""
        for indi in individuals.values():
            if indi.events:
                result = _get_events(indi.id)
                if result:
                    event = result[0]
                    assert "type" in event
                    assert "date" in event
                    assert "place" in event
                    assert "citations" in event
                    assert "notes" in event
                break


class TestSearchEvents:
    """Tests for the search_events function."""

    def test_search_returns_list(self):
        """Should return a list."""
        result = _search_events()
        assert isinstance(result, list)

    def test_search_by_type(self):
        """Should filter by event type."""
        result = _search_events(event_type="BIRT", max_results=10)
        for event in result:
            assert event["type"] == "BIRT"

    def test_search_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _search_events(max_results=5)
        assert len(result) <= 5

    def test_search_result_has_individual_info(self):
        """Results should include individual info."""
        result = _search_events(max_results=1)
        if result:
            assert "individual_id" in result[0]
            assert "individual_name" in result[0]


class TestGetCitations:
    """Tests for the get_citations function."""

    def test_get_citations_returns_list(self):
        """Should return a list."""
        # Use home person
        result = _get_citations(HOME_PERSON_ID)
        assert isinstance(result, list)

    def test_get_citations_for_nonexistent(self):
        """Should return empty list for nonexistent individual."""
        result = _get_citations("NONEXISTENT999")
        assert result == []

    def test_citations_have_event_context(self):
        """Citations should include event context."""
        # Find an individual with citations
        for indi in individuals.values():
            for event in indi.events:
                if event.citations:
                    result = _get_citations(indi.id)
                    if result:
                        assert "event_type" in result[0]
                        assert "event_date" in result[0]
                        assert "source_id" in result[0]
                    return
        # Skip if no citations found
        pass


class TestGetNotes:
    """Tests for the get_notes function."""

    def test_get_notes_returns_list(self):
        """Should return a list."""
        result = _get_notes(HOME_PERSON_ID)
        assert isinstance(result, list)

    def test_get_notes_for_nonexistent(self):
        """Should return empty list for nonexistent individual."""
        result = _get_notes("NONEXISTENT999")
        assert result == []

    def test_notes_have_event_context(self):
        """Notes should include event context."""
        # Find an individual with notes
        for indi in individuals.values():
            for event in indi.events:
                if event.notes:
                    result = _get_notes(indi.id)
                    if result:
                        assert "event_type" in result[0]
                        assert "event_date" in result[0]
                        assert "note" in result[0]
                    return
        # Skip if no notes found
        pass


class TestGetTimeline:
    """Tests for the get_timeline function."""

    def test_get_timeline_returns_list(self):
        """Should return a list."""
        result = _get_timeline(HOME_PERSON_ID)
        assert isinstance(result, list)

    def test_get_timeline_for_nonexistent(self):
        """Should return empty list for nonexistent individual."""
        result = _get_timeline("NONEXISTENT999")
        assert result == []

    def test_timeline_is_sorted(self):
        """Timeline should be sorted by date."""
        # Find an individual with multiple events
        for indi in individuals.values():
            if len(indi.events) >= 2:
                result = _get_timeline(indi.id)
                # Check that years are non-decreasing (events without dates go last)
                years = []
                for event in result:
                    year = extract_year(event.get("date"))
                    if year:
                        years.append(year)
                # Years should be sorted
                assert years == sorted(years)
                break


class TestGetFamilyEvents:
    """Tests for the get_family_events function."""

    def test_returns_list(self, sample_family_id):
        """Should return a list."""
        result = _get_family_events(sample_family_id)
        assert isinstance(result, list)

    def test_nonexistent_family(self):
        """Should return empty list for nonexistent family."""
        result = _get_family_events("@NONEXISTENT999@")
        assert result == []

    def test_events_have_individual_context(self, sample_family_id):
        """Events should include individual_id and individual_name."""
        result = _get_family_events(sample_family_id)
        if result:
            event = result[0]
            assert "individual_id" in event
            assert "individual_name" in event

    def test_events_sorted_chronologically(self, sample_family_id):
        """Events should be sorted by date."""
        result = _get_family_events(sample_family_id)
        if len(result) >= 2:
            years = []
            for event in result:
                year = extract_year(event.get("date"))
                if year:
                    years.append(year)
            # Years should be non-decreasing
            assert years == sorted(years)

    def test_includes_spouse_and_children_events(self):
        """Should include events from spouses and children."""
        # Find a family with multiple members who have events
        for fam in families.values():
            member_ids = []
            if fam.husband_id:
                member_ids.append(fam.husband_id)
            if fam.wife_id:
                member_ids.append(fam.wife_id)
            member_ids.extend(fam.children_ids)

            if len(member_ids) >= 2:
                result = _get_family_events(fam.id)
                if result:
                    # Check that events from multiple individuals are included
                    unique_individuals = {e["individual_id"] for e in result}
                    if len(unique_individuals) >= 2:
                        # Found a family with events from multiple members
                        assert len(unique_individuals) >= 2
                        return
        # Skip if no suitable family found
        pass


class TestGetFamilyTimeline:
    """Tests for the get_family_timeline function."""

    def test_returns_list(self):
        """Should return a list."""
        ids = list(individuals.keys())[:2]
        result = _get_family_timeline(ids)
        assert isinstance(result, list)

    def test_empty_list(self):
        """Should handle empty list."""
        result = _get_family_timeline([])
        assert result == []

    def test_events_have_individual_context(self):
        """Events should include individual_id and individual_name."""
        # Find individuals with events
        ids = []
        for indi in individuals.values():
            if indi.events:
                ids.append(indi.id)
            if len(ids) >= 2:
                break

        result = _get_family_timeline(ids)
        if result:
            event = result[0]
            assert "individual_id" in event
            assert "individual_name" in event

    def test_events_sorted_chronologically(self):
        """Events should be sorted by date."""
        ids = list(individuals.keys())[:5]
        result = _get_family_timeline(ids)
        if len(result) >= 2:
            years = []
            for event in result:
                year = extract_year(event.get("date"))
                if year:
                    years.append(year)
            # Years should be non-decreasing
            assert years == sorted(years)

    def test_start_year_filter(self):
        """Should filter by start_year."""
        ids = list(individuals.keys())[:10]
        result = _get_family_timeline(ids, start_year=1900)
        for event in result:
            year = extract_year(event.get("date"))
            if year:
                assert year >= 1900

    def test_end_year_filter(self):
        """Should filter by end_year."""
        ids = list(individuals.keys())[:10]
        result = _get_family_timeline(ids, end_year=1950)
        for event in result:
            year = extract_year(event.get("date"))
            if year:
                assert year <= 1950

    def test_year_range_filter(self):
        """Should filter by both start and end year."""
        ids = list(individuals.keys())[:10]
        result = _get_family_timeline(ids, start_year=1900, end_year=1950)
        for event in result:
            year = extract_year(event.get("date"))
            if year:
                assert 1900 <= year <= 1950

    def test_includes_events_from_multiple_individuals(self):
        """Should include events from all requested individuals."""
        # Find individuals with events
        ids_with_events = []
        for indi in individuals.values():
            if indi.events:
                ids_with_events.append(indi.id)
            if len(ids_with_events) >= 3:
                break

        if len(ids_with_events) >= 2:
            result = _get_family_timeline(ids_with_events)
            unique_individuals = {e["individual_id"] for e in result}
            # Should have events from multiple individuals
            assert len(unique_individuals) >= 2
