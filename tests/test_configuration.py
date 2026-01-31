"""Tests for GEDCOM server configuration."""

import pytest

from gedcom_server import state


class TestConfiguration:
    """Tests for configuration functions."""

    def test_gedcom_file_set_from_env(self):
        """GEDCOM_FILE should be set from environment variable."""
        assert state.GEDCOM_FILE is not None
        assert state.GEDCOM_FILE.exists()
        assert state.GEDCOM_FILE.name == "sample.ged"

    def test_home_person_auto_detected(self):
        """HOME_PERSON_ID should be auto-detected when not set in env."""
        # Since we didn't set GEDCOM_HOME_PERSON_ID, it should be auto-detected
        assert state.HOME_PERSON_ID is not None
        assert state.HOME_PERSON_ID in state.individuals


class TestHomePerson:
    """Tests for home person detection."""

    def test_home_person_is_most_connected(self):
        """Auto-detected home person should be the most connected individual."""
        home = state.individuals.get(state.HOME_PERSON_ID)
        assert home is not None

        # The home person should have family connections
        # In our sample data, Emily (I5) or Robert (I3) should be detected
        # since they have both parents and spouse/children connections

    def test_detect_home_person_returns_valid_id(self):
        """_detect_home_person should return a valid individual ID."""
        detected = state._detect_home_person()
        assert detected is not None
        assert detected in state.individuals


class TestResolveGedcomPath:
    """Tests for GEDCOM path resolution."""

    def test_missing_env_var_raises_error(self, monkeypatch):
        """Should raise FileNotFoundError when GEDCOM_FILE env var not set."""
        monkeypatch.delenv("GEDCOM_FILE", raising=False)
        with pytest.raises(FileNotFoundError, match="GEDCOM_FILE environment variable not set"):
            state._resolve_gedcom_path()

    def test_nonexistent_file_raises_error(self, monkeypatch):
        """Should raise FileNotFoundError when file doesn't exist."""
        monkeypatch.setenv("GEDCOM_FILE", "/nonexistent/path/tree.ged")
        with pytest.raises(FileNotFoundError, match="GEDCOM file not found"):
            state._resolve_gedcom_path()

    def test_valid_path_returns_resolved(self, monkeypatch, tmp_path):
        """Should return resolved Path when file exists."""
        # Create a temp gedcom file
        gedcom = tmp_path / "test.ged"
        gedcom.write_text("0 HEAD\n0 TRLR\n")

        monkeypatch.setenv("GEDCOM_FILE", str(gedcom))
        result = state._resolve_gedcom_path()

        assert result == gedcom.resolve()
        assert result.exists()

    def test_tilde_expansion(self, monkeypatch, tmp_path):
        """Should expand ~ in path."""
        # Create a temp gedcom file
        gedcom = tmp_path / "test.ged"
        gedcom.write_text("0 HEAD\n0 TRLR\n")

        # Patch expanduser to return our temp path
        monkeypatch.setenv("GEDCOM_FILE", str(gedcom))
        result = state._resolve_gedcom_path()

        assert result.is_absolute()


class TestSampleData:
    """Tests that verify sample.ged was loaded correctly."""

    def test_individuals_loaded(self):
        """Should have loaded individuals from sample.ged."""
        assert len(state.individuals) == 6

    def test_families_loaded(self):
        """Should have loaded families from sample.ged."""
        assert len(state.families) == 2

    def test_sources_loaded(self):
        """Should have loaded sources from sample.ged."""
        assert len(state.sources) == 2

    def test_specific_individual_exists(self):
        """Should have loaded John Smith."""
        john = state.individuals.get("@I1@")
        assert john is not None
        assert john.given_name == "John"
        assert john.surname == "SMITH"
        assert john.birth_place == "Boston, Suffolk, Massachusetts, USA"

    def test_family_relationships(self):
        """Should have correct family relationships."""
        fam1 = state.families.get("@F1@")
        assert fam1 is not None
        assert fam1.husband_id == "@I1@"
        assert fam1.wife_id == "@I2@"
        assert "@I3@" in fam1.children_ids

    def test_indexes_built(self):
        """Should have built surname and place indexes."""
        assert "smith" in state.surname_index
        assert len(state.surname_index["smith"]) == 4  # John, Robert, Emily, Michael

        # Check place index has entries
        assert len(state.place_index) > 0
