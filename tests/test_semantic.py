"""Tests for semantic search functionality."""

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from gedcom_server import semantic
from gedcom_server.state import individuals


class TestIsEnabled:
    """Tests for is_enabled() function."""

    def test_disabled_by_default(self):
        """Semantic search should be disabled when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove SEMANTIC_SEARCH_ENABLED if it exists
            os.environ.pop("SEMANTIC_SEARCH_ENABLED", None)
            assert semantic.is_enabled() is False

    def test_enabled_when_true(self):
        """Semantic search enabled when env var is 'true'."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "true"}):
            assert semantic.is_enabled() is True

    def test_enabled_case_insensitive(self):
        """Env var should be case-insensitive."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "TRUE"}):
            assert semantic.is_enabled() is True
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "True"}):
            assert semantic.is_enabled() is True

    def test_disabled_when_false(self):
        """Semantic search disabled when env var is 'false'."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "false"}):
            assert semantic.is_enabled() is False

    def test_disabled_when_other_value(self):
        """Semantic search disabled for any value other than 'true'."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "yes"}):
            assert semantic.is_enabled() is False
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "1"}):
            assert semantic.is_enabled() is False


class TestBuildEmbeddingText:
    """Tests for _build_embedding_text() function."""

    def test_builds_text_for_individual(self, sample_individual_id):
        """Should build non-empty text for a valid individual."""
        text = semantic._build_embedding_text(sample_individual_id)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_includes_name(self, sample_individual_id):
        """Embedding text should include the individual's name."""
        indi = individuals[sample_individual_id]
        text = semantic._build_embedding_text(sample_individual_id)
        # Should contain at least part of the name
        if indi.given_name:
            assert indi.given_name in text
        if indi.surname:
            assert indi.surname in text

    def test_includes_vital_info(self, sample_individual_id):
        """Embedding text should include birth/death info if available."""
        indi = individuals[sample_individual_id]
        text = semantic._build_embedding_text(sample_individual_id)
        if indi.birth_date:
            assert indi.birth_date in text
        if indi.birth_place:
            assert indi.birth_place in text

    def test_includes_events(self, individual_with_events):
        """Embedding text should include event information."""
        text = semantic._build_embedding_text(individual_with_events.id)
        # Should contain at least one event type
        has_event = False
        for event in individual_with_events.events:
            if event.type in text:
                has_event = True
                break
        assert has_event, "Expected at least one event type in embedding text"

    def test_includes_notes(self, individual_with_notes):
        """Embedding text should include notes from events."""
        text = semantic._build_embedding_text(individual_with_notes.id)
        # Find the note content and check it's in the text
        for event in individual_with_notes.events:
            for note in event.notes:
                assert note in text, f"Expected note '{note[:50]}...' in embedding text"
                return  # Just need to verify one note

    def test_returns_empty_for_invalid_id(self):
        """Should return empty string for invalid individual ID."""
        text = semantic._build_embedding_text("@INVALID@")
        assert text == ""

    def test_includes_parent_context(self, individual_with_parents):
        """Embedding text should include parent names."""
        text = semantic._build_embedding_text(individual_with_parents.id)
        assert "Parents:" in text


class TestSemanticSearch:
    """Tests for _semantic_search() function."""

    def test_returns_error_when_disabled(self):
        """Should return error dict when semantic search is disabled."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "false"}):
            result = semantic._semantic_search("test query")
            assert "error" in result
            assert result["error"] == "Semantic search not enabled"
            assert result["results"] == []

    def test_returns_error_when_no_embeddings(self):
        """Should return error when embeddings not built."""
        # Save original state
        orig_embeddings = semantic._embeddings
        orig_ids = semantic._embedding_ids

        try:
            # Clear embeddings
            semantic._embeddings = None
            semantic._embedding_ids = []

            with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "true"}):
                result = semantic._semantic_search("test query")
                assert "error" in result
                assert "not built" in result["error"]
        finally:
            # Restore original state
            semantic._embeddings = orig_embeddings
            semantic._embedding_ids = orig_ids

    def test_clamps_max_results(self):
        """max_results should be clamped to valid range."""
        with (
            patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "true"}),
            patch.object(semantic, "_embeddings", np.zeros((10, 384))),
            patch.object(semantic, "_embedding_ids", [f"@I{i}@" for i in range(10)]),
            patch.object(semantic, "_embedding_texts", ["text"] * 10),
            patch.object(semantic, "_encoder") as mock_encoder,
        ):
            mock_encoder.encode.return_value = np.zeros((1, 384))
            # Test max > 100 gets clamped
            result = semantic._semantic_search("test", max_results=200)
            # Should work without error (clamped internally)
            assert isinstance(result, dict)


class TestCacheOperations:
    """Tests for cache save/load functionality."""

    def test_get_cache_path(self, tmp_path):
        """Cache path should be based on GEDCOM file path."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n")

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            cache_path = semantic._get_cache_path()
            assert cache_path == test_ged.with_suffix(".ged.embeddings.npz")

    def test_get_cache_path_none_when_no_gedcom(self):
        """Cache path should be None when GEDCOM_FILE not set."""
        with patch.object(semantic.state, "GEDCOM_FILE", None):
            assert semantic._get_cache_path() is None

    def test_compute_gedcom_hash(self, tmp_path):
        """Should compute consistent hash for same file content."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n1 SOUR Test\n")

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            hash1 = semantic._compute_gedcom_hash()
            hash2 = semantic._compute_gedcom_hash()
            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex digest

    def test_cache_round_trip(self, tmp_path):
        """Should save and load cache correctly."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n1 SOUR Test\n")

        # Create test embeddings
        test_embeddings = np.random.rand(5, 384).astype(np.float32)
        test_ids = ["@I1@", "@I2@", "@I3@", "@I4@", "@I5@"]
        test_texts = ["text1", "text2", "text3", "text4", "text5"]

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            # Set up state for saving
            semantic._embeddings = test_embeddings
            semantic._embedding_ids = test_ids
            semantic._embedding_texts = test_texts

            # Save cache
            semantic._save_cache()

            # Verify file was created
            cache_path = semantic._get_cache_path()
            assert cache_path.exists()

            # Clear state
            semantic._embeddings = None
            semantic._embedding_ids = []
            semantic._embedding_texts = []

            # Load cache
            success = semantic._load_cache()
            assert success is True
            assert np.allclose(semantic._embeddings, test_embeddings)
            assert semantic._embedding_ids == test_ids
            assert semantic._embedding_texts == test_texts

    def test_cache_invalidation_on_gedcom_change(self, tmp_path):
        """Cache should be invalidated when GEDCOM file changes."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n1 SOUR Test\n")

        test_embeddings = np.random.rand(5, 384).astype(np.float32)
        test_ids = ["@I1@", "@I2@", "@I3@", "@I4@", "@I5@"]
        test_texts = ["text1", "text2", "text3", "text4", "text5"]

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            # Set up and save
            semantic._embeddings = test_embeddings
            semantic._embedding_ids = test_ids
            semantic._embedding_texts = test_texts
            semantic._save_cache()

            # Modify GEDCOM file
            test_ged.write_text("0 HEAD\n1 SOUR Modified\n")

            # Clear state
            semantic._embeddings = None
            semantic._embedding_ids = []
            semantic._embedding_texts = []

            # Load should fail due to hash mismatch
            success = semantic._load_cache()
            assert success is False

    def test_load_cache_returns_false_when_missing(self, tmp_path):
        """_load_cache should return False when cache file doesn't exist."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n")

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            # No cache file exists
            success = semantic._load_cache()
            assert success is False


class TestBuildEmbeddings:
    """Tests for build_embeddings() function."""

    def test_skips_when_disabled(self):
        """build_embeddings should do nothing when disabled."""
        with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "false"}):
            # Clear any existing state
            semantic._embeddings = None
            semantic._embedding_ids = []

            semantic.build_embeddings()

            # Should remain None/empty
            assert semantic._embeddings is None
            assert semantic._embedding_ids == []

    def test_loads_from_cache_when_valid(self, tmp_path):
        """Should load from cache instead of rebuilding."""
        test_ged = tmp_path / "test.ged"
        test_ged.write_text("0 HEAD\n")

        # Create a cache file
        test_embeddings = np.random.rand(3, 384).astype(np.float32)
        cache_path = test_ged.with_suffix(".ged.embeddings.npz")

        with patch.object(semantic.state, "GEDCOM_FILE", test_ged):
            np.savez_compressed(
                cache_path,
                gedcom_hash=semantic._compute_gedcom_hash(),
                model_name=semantic.MODEL_NAME,
                embeddings=test_embeddings,
                ids=np.array(["@I1@", "@I2@", "@I3@"], dtype=object),
                texts=np.array(["t1", "t2", "t3"], dtype=object),
            )

            with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "true"}):
                semantic._embeddings = None
                semantic._embedding_ids = []
                semantic._embedding_texts = []

                semantic.build_embeddings()

                # Should have loaded from cache (fast path)
                # Verify the expected number of embeddings were loaded
                assert len(semantic._embedding_ids) == 3


class TestResultsFormat:
    """Tests for search result format."""

    def test_result_structure(self):
        """Search results should have expected structure."""
        # Create mock data
        mock_embeddings = np.random.rand(3, 384).astype(np.float32)
        mock_embeddings = mock_embeddings / np.linalg.norm(mock_embeddings, axis=1, keepdims=True)
        mock_ids = (
            list(individuals.keys())[:3] if len(individuals) >= 3 else list(individuals.keys())
        )
        mock_texts = ["Test text 1", "Test text 2", "Test text 3"][: len(mock_ids)]

        if not mock_ids:
            pytest.skip("No individuals in test data")

        # Save original state
        orig_embeddings = semantic._embeddings
        orig_ids = semantic._embedding_ids
        orig_texts = semantic._embedding_texts
        orig_encoder = semantic._encoder

        try:
            semantic._embeddings = mock_embeddings[: len(mock_ids)]
            semantic._embedding_ids = mock_ids
            semantic._embedding_texts = mock_texts

            # Mock encoder
            mock_enc = MagicMock()
            mock_enc.encode.return_value = np.random.rand(1, 384).astype(np.float32)
            semantic._encoder = mock_enc

            with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": "true"}):
                result = semantic._semantic_search("test query", max_results=3)

                assert "query" in result
                assert "result_count" in result
                assert "results" in result
                assert result["query"] == "test query"
                assert isinstance(result["results"], list)

                if result["results"]:
                    first = result["results"][0]
                    assert "individual_id" in first
                    assert "name" in first
                    assert "relevance_score" in first
                    assert "snippet" in first
        finally:
            semantic._embeddings = orig_embeddings
            semantic._embedding_ids = orig_ids
            semantic._embedding_texts = orig_texts
            semantic._encoder = orig_encoder
