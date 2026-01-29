"""Tests for surname index data integrity."""

from gedcom_server.state import surname_index


class TestSurnamesResourceLogic:
    """Tests for surnames index data integrity."""

    def test_surname_index_has_data(self):
        """Should have surname data."""
        assert len(surname_index) > 0

    def test_surname_counts_are_positive(self):
        """All surname counts should be positive."""
        for surname, ids in surname_index.items():
            assert len(ids) > 0, f"Surname {surname} has no individuals"

    def test_surnames_are_strings(self):
        """All surname keys should be strings."""
        for surname in surname_index:
            assert isinstance(surname, str)
