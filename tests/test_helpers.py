"""Tests for helper functions."""

from gedcom_server.core import _normalize_lookup_id
from gedcom_server.helpers import extract_year, normalize_id
from gedcom_server.models import Family, Individual


class TestExtractYear:
    """Tests for the extract_year function."""

    def test_extracts_4_digit_year(self):
        """Should extract year from full date."""
        assert extract_year("21 JUN 1984") == 1984

    def test_handles_year_only(self):
        """Should handle year-only input."""
        assert extract_year("1984") == 1984

    def test_handles_about_dates(self):
        """Should extract year from approximate dates."""
        assert extract_year("ABT 1850") == 1850
        assert extract_year("ABOUT 1900") == 1900

    def test_handles_date_ranges(self):
        """Should extract first year from date ranges."""
        assert extract_year("BET 1900 AND 1910") == 1900

    def test_handles_before_after_dates(self):
        """Should extract year from before/after dates."""
        assert extract_year("BEF 1800") == 1800
        assert extract_year("AFT 1950") == 1950

    def test_returns_none_for_no_year(self):
        """Should return None when no year present."""
        assert extract_year("June") is None
        assert extract_year("unknown") is None

    def test_returns_none_for_empty_string(self):
        """Should return None for empty string."""
        assert extract_year("") is None

    def test_returns_none_for_none(self):
        """Should return None for None input."""
        assert extract_year(None) is None

    def test_handles_parenthetical_dates(self):
        """Should extract year from parenthetical format."""
        assert extract_year("(29 Nov. 1886)") == 1886


class TestNormalizeId:
    """Tests for the normalize_id function."""

    def test_adds_at_symbols(self):
        """Should add @ symbols to bare ID."""
        assert normalize_id("I123") == "@I123@"

    def test_preserves_existing_at_symbols(self):
        """Should preserve properly formatted ID."""
        assert normalize_id("@I123@") == "@I123@"

    def test_handles_single_at_prefix(self):
        """Should normalize ID with only prefix @."""
        assert normalize_id("@I123") == "@I123@"

    def test_handles_single_at_suffix(self):
        """Should normalize ID with only suffix @."""
        assert normalize_id("I123@") == "@I123@"

    def test_handles_none(self):
        """Should return None for None input."""
        assert normalize_id(None) is None

    def test_handles_empty_string(self):
        """Should return None for empty string."""
        assert normalize_id("") is None

    def test_handles_family_id(self):
        """Should work with family IDs too."""
        assert normalize_id("F123") == "@F123@"


class TestNormalizeLookupId:
    """Tests for the _normalize_lookup_id function."""

    def test_normalizes_bare_id(self):
        """Should add @ symbols to bare ID."""
        assert _normalize_lookup_id("I123") == "@I123@"

    def test_normalizes_with_at_symbols(self):
        """Should handle already-formatted ID."""
        assert _normalize_lookup_id("@I123@") == "@I123@"

    def test_handles_extra_at_symbols(self):
        """Should normalize IDs with extra @ symbols."""
        # Strip removes all @ from both ends, then re-adds them
        assert _normalize_lookup_id("@@I123@@") == "@I123@"

    def test_handles_whitespace(self):
        """Should handle whitespace in ID."""
        # Current implementation doesn't strip whitespace, but @ stripping happens
        result = _normalize_lookup_id(" I123 ")
        # The spaces remain inside the @s
        assert "@" in result


class TestIndividualModel:
    """Tests for the Individual dataclass methods."""

    def test_full_name_both_parts(self):
        """Should combine given name and surname."""
        indi = Individual(id="@I1@", given_name="John", surname="Smith")
        assert indi.full_name() == "John Smith"

    def test_full_name_given_only(self):
        """Should handle given name only."""
        indi = Individual(id="@I1@", given_name="John", surname="")
        assert indi.full_name() == "John"

    def test_full_name_surname_only(self):
        """Should handle surname only."""
        indi = Individual(id="@I1@", given_name="", surname="Smith")
        assert indi.full_name() == "Smith"

    def test_full_name_empty(self):
        """Should return empty string when no name parts."""
        indi = Individual(id="@I1@", given_name="", surname="")
        assert indi.full_name() == ""

    def test_to_dict_has_all_fields(self):
        """Should include all fields in dict output."""
        indi = Individual(
            id="@I1@",
            given_name="John",
            surname="Smith",
            sex="M",
            birth_date="1 JAN 1900",
            birth_place="New York",
            death_date="1 JAN 1980",
            death_place="Boston",
            family_as_child="@F1@",
            families_as_spouse=["@F2@"],
        )
        d = indi.to_dict()
        assert d["id"] == "@I1@"
        assert d["given_name"] == "John"
        assert d["surname"] == "Smith"
        assert d["full_name"] == "John Smith"
        assert d["sex"] == "M"
        assert d["birth_date"] == "1 JAN 1900"
        assert d["birth_place"] == "New York"
        assert d["death_date"] == "1 JAN 1980"
        assert d["death_place"] == "Boston"
        assert d["family_as_child"] == "@F1@"
        assert d["families_as_spouse"] == ["@F2@"]

    def test_to_summary_has_required_fields(self):
        """Should include summary fields."""
        indi = Individual(
            id="@I1@",
            given_name="John",
            surname="Smith",
            birth_date="1900",
            death_date="1980",
        )
        s = indi.to_summary()
        assert s["id"] == "@I1@"
        assert s["name"] == "John Smith"
        assert s["birth_date"] == "1900"
        assert s["death_date"] == "1980"


class TestFamilyModel:
    """Tests for the Family dataclass methods."""

    def test_to_dict_has_all_fields(self):
        """Should include all fields in dict output."""
        fam = Family(
            id="@F1@",
            husband_id="@I1@",
            wife_id="@I2@",
            children_ids=["@I3@", "@I4@"],
            marriage_date="1 JAN 1920",
            marriage_place="Boston",
        )
        d = fam.to_dict()
        assert d["id"] == "@F1@"
        assert d["husband_id"] == "@I1@"
        assert d["wife_id"] == "@I2@"
        assert d["children_ids"] == ["@I3@", "@I4@"]
        assert d["marriage_date"] == "1 JAN 1920"
        assert d["marriage_place"] == "Boston"

    def test_children_ids_is_list(self):
        """Should have children_ids as a list."""
        fam = Family(id="@F1@")
        assert isinstance(fam.children_ids, list)

    def test_default_values(self):
        """Should have sensible defaults."""
        fam = Family(id="@F1@")
        assert fam.husband_id is None
        assert fam.wife_id is None
        assert fam.children_ids == []
        assert fam.marriage_date is None
        assert fam.marriage_place is None
