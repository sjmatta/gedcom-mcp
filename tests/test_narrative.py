"""Tests for narrative content features (biography, search, repositories)."""

from gedcom_server.models import Individual, Repository
from gedcom_server.narrative import (
    _create_snippet,
    _get_biography,
    _get_repositories,
    _search_narrative,
)
from gedcom_server.state import HOME_PERSON_ID


class TestRepositoryDataclass:
    """Tests for the Repository dataclass."""

    def test_repository_to_dict(self):
        """Should include all fields in dict output."""
        repo = Repository(
            id="@R1@",
            name="Ancestry.com",
            address="123 Main St",
            url="https://ancestry.com",
        )
        d = repo.to_dict()
        assert d["id"] == "@R1@"
        assert d["name"] == "Ancestry.com"
        assert d["address"] == "123 Main St"
        assert d["url"] == "https://ancestry.com"

    def test_repository_defaults(self):
        """Should have sensible defaults."""
        repo = Repository(id="@R1@")
        assert repo.name is None
        assert repo.address is None
        assert repo.url is None


class TestIndividualNotes:
    """Tests for individual-level notes field."""

    def test_individual_has_notes_field(self):
        """Individual dataclass should have notes field."""
        indi = Individual(id="@I1@")
        assert hasattr(indi, "notes")
        assert indi.notes == []

    def test_individual_to_dict_includes_notes(self):
        """to_dict should include notes."""
        indi = Individual(id="@I1@", notes=["Note 1", "Note 2"])
        d = indi.to_dict()
        assert "notes" in d
        assert d["notes"] == ["Note 1", "Note 2"]


class TestGetBiography:
    """Tests for the get_biography function."""

    def test_get_biography_for_nonexistent(self):
        """Should return None for nonexistent individual."""
        result = _get_biography("NONEXISTENT999")
        assert result is None

    def test_biography_has_required_fields(self):
        """Biography should have all required fields."""
        result = _get_biography(HOME_PERSON_ID)
        assert result is not None
        required_fields = [
            "id",
            "name",
            "vital_summary",
            "birth",
            "death",
            "sex",
            "parents",
            "spouses",
            "children",
            "events",
            "notes",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_biography_birth_death_structure(self):
        """Birth and death should be dicts with date and place."""
        result = _get_biography(HOME_PERSON_ID)
        assert result is not None
        assert "date" in result["birth"]
        assert "place" in result["birth"]
        assert "date" in result["death"]
        assert "place" in result["death"]

    def test_biography_family_are_names(self):
        bio = _get_biography("I3")
        assert bio["parents"] == ["John SMITH", "Mary JONES"]
        assert [spouse["name"] for spouse in bio["spouses"]] == ["Sarah Ann WILLIAMS"]
        assert bio["children"] == ["Emily Rose SMITH", "Michael James SMITH"]

    def test_biography_events_have_citations(self):
        bio = _get_biography("I1")
        birth = next(event for event in bio["events"] if event["type"] == "BIRT")
        assert birth["citations"] == [{"source": "Massachusetts Vital Records", "page": "Page 42"}]
        # Okay if no citations found

    def test_biography_includes_individual_notes(self):
        assert _get_biography("I3")["notes"] == [
            "Robert was a dedicated family man who loved hiking and photography."
        ]
        # Okay if no notes found


class TestSearchNarrative:
    """Tests for the search_narrative function."""

    def test_search_respects_max_results(self):
        """Should respect max_results parameter."""
        result = _search_narrative("a", max_results=5)
        assert len(result["results"]) <= 5

    def test_search_finds_individual_notes(self):
        result = _search_narrative("hiking")
        assert result["query"] == "hiking"
        assert result["result_count"] == len(result["results"]) == 1
        note = result["results"][0]
        assert note["individual_id"] == "@I3@"
        assert note["individual_name"] == "Robert John SMITH"
        assert note["source"] == "note"
        assert "**hiking**" in note["snippet"]
        assert "hiking and photography" in note["full_text"]

    def test_search_case_insensitive(self):
        upper = _search_narrative("HIKING")
        lower = _search_narrative("hiking")
        assert upper["result_count"] == lower["result_count"] == 1
        assert upper["results"] == lower["results"]


class TestCreateSnippet:
    """Tests for the snippet creation helper."""

    def test_creates_snippet_with_highlight(self):
        """Should highlight the matched query."""
        text = "This is a test string with some content."
        snippet = _create_snippet(text, "test")
        assert "**test**" in snippet

    def test_snippet_has_context(self):
        """Should include context around the match."""
        text = "A" * 100 + "MATCH" + "B" * 100
        snippet = _create_snippet(text, "match")
        assert "**MATCH**" in snippet
        assert "A" in snippet  # Has leading context
        assert "B" in snippet  # Has trailing context

    def test_snippet_with_ellipsis(self):
        """Should add ellipsis when truncating."""
        text = "A" * 100 + "MATCH" + "B" * 100
        snippet = _create_snippet(text, "match", context_chars=10)
        assert "..." in snippet


class TestGetRepositories:
    """Tests for the get_repositories function."""

    def test_repository_structure(self, monkeypatch):
        repo = Repository(
            id="@R1@", name="Archives", address="123 Main St", url="https://example.com"
        )
        monkeypatch.setattr("gedcom_server.state.repositories", {repo.id: repo})
        assert _get_repositories() == [repo.to_dict()]
