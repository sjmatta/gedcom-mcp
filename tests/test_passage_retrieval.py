"""Regression checks for complete evidence, unique people, and ranking failures."""

import re
from unittest.mock import Mock

import numpy as np
import pytest

from gedcom_server import semantic, state
from gedcom_server.models import Citation, Event, Individual
from gedcom_server.retrieval import (
    BM25,
    diverse_top_indices,
    matching_snippet,
    split_passages,
    top_indices,
)


class WordTokenizer:
    def encode(self, text, **kwargs):
        return text.split()

    def __call__(self, text, **kwargs):
        return {"offset_mapping": [match.span() for match in re.finditer(r"\S+", text)]}


def test_long_note_has_complete_overlapping_coverage():
    encoder = Mock(tokenizer=WordTokenizer(), max_seq_length=128)
    words = [f"word{i}" for i in range(1000)] + ["Život", "🧬", "hidden-evidence"]
    passages = split_passages(" ".join(words), "Alice Smith. ", encoder)
    covered = {word for passage in passages for word in passage.split()}
    assert set(words) <= covered
    assert all(len(passage.split()) <= 128 for passage in passages)
    assert "hidden-evidence" in passages[-1]
    assert len(set(passages[0].split()) & set(passages[1].split())) > 2


def test_lexical_retrieval_keeps_names_dates_and_negation():
    index = BM25(["Maria Silva married in Porto in 1892", "Maria Silva married in Porto in 1893"])
    assert top_indices(index.scores("Maria Silva Porto 1893"), 1) == [1]
    assert BM25(["Convicted of arson", "Not convicted of arson"]).scores("not")[1] > 0
    assert top_indices(np.ones(10), 3) == [0, 1, 2]


def test_snippet_shows_evidence_late_in_matching_passage():
    text = (
        "Routine household repairs. " * 30 + "Sheltered political fugitives in a cellar in Odessa."
    )
    snippet = matching_snippet(text, "Who sheltered political fugitives in Odessa?")
    assert "political fugitives" in snippet
    assert "Odessa" in snippet
    assert len(snippet) <= 606


def test_very_long_biography_cannot_crowd_out_other_people():
    scores = np.concatenate([np.ones(1000), np.array([0.9, 0.8])])
    ids = ["@A@"] * 1000 + ["@B@", "@C@"]
    assert diverse_top_indices(scores, ids, 4) == [0, 1, 1000, 1001]


def test_refresh_encodes_only_changed_passages(monkeypatch):
    old = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    monkeypatch.setattr(
        semantic, "_previous_index", (["@A@", "@B@"], ["unchanged", "deleted"], old)
    )
    encoder = Mock()
    encoder.encode_document.return_value = np.array([[0.5, 0.5]], dtype=np.float32)
    vectors = semantic._encode_changed_passages(encoder, ["@C@", "@A@"], ["new", "unchanged"])
    assert np.array_equal(vectors, np.array([[0.5, 0.5], [1.0, 0.0]]))
    assert encoder.encode_document.call_args.args[0] == ["new"]
    encoder.reset_mock()
    vectors = semantic._encode_changed_passages(encoder, ["@A@"], ["unchanged"])
    assert np.array_equal(vectors, old[:1])
    encoder.encode_document.assert_not_called()


@pytest.fixture
def search_state(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_RERANK_ENABLED", "false")
    monkeypatch.setattr(
        state,
        "individuals",
        {
            "@A@": Individual("@A@", "Alice", "Abbott"),
            "@B@": Individual("@B@", "Bob", "Bennett"),
        },
    )
    monkeypatch.setattr(semantic, "_embeddings", np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]))
    monkeypatch.setattr(semantic, "_embedding_ids", ["@A@", "@A@", "@B@"])
    monkeypatch.setattr(
        semantic,
        "_embedding_texts",
        ["Alice mined coal in Cardiff", "Alice made bread in Leeds", "Bob mined coal in Cardiff"],
    )
    monkeypatch.setattr(
        semantic,
        "_embedding_evidence",
        [
            {"kind": "event", "event_type": "OCCU", "source_ids": ["@S1@"]},
            {"kind": "note", "note_index": 0},
            {"kind": "note", "note_index": 1},
        ],
    )
    monkeypatch.setattr(semantic, "_lexical", None)
    encoder = Mock()
    encoder.encode_query.return_value = np.array([[1.0, 0.0]])
    monkeypatch.setattr(semantic, "_encoder", encoder)


def test_multiple_matching_passages_return_unique_people_with_evidence(search_state):
    response = semantic._semantic_search("coal in Cardiff", max_results=2)
    assert len(response["results"]) == 2
    assert {row["individual_id"] for row in response["results"]} == {"@A@", "@B@"}
    alice = next(row for row in response["results"] if row["individual_id"] == "@A@")
    assert "Cardiff" in alice["snippet"]
    assert alice["evidence"][0]["source_ids"] == ["@S1@"]
    assert response["score_type"] == "reciprocal_rank_fusion"


def test_reranker_reorders_people_and_failure_is_visible(search_state, monkeypatch):
    monkeypatch.setenv("SEMANTIC_RERANK_ENABLED", "true")
    reranker = Mock()
    reranker.predict.return_value = np.array([-2.0, 4.0])
    monkeypatch.setattr(semantic, "_get_reranker", lambda: reranker)
    response = semantic._semantic_search("coal in Cardiff")
    assert response["results"][0]["individual_id"] == "@B@"
    assert response["search_mode"] == "hybrid_reranked"
    assert response["score_type"] == "cross_encoder_logit"
    reranker.predict.return_value = np.array([np.nan, 4.0])
    response = semantic._semantic_search("coal in Cardiff")
    assert response["search_mode"] == "hybrid"
    assert "warning" in response
    assert all(np.isfinite(row["relevance_score"]) for row in response["results"])


def test_lexical_index_rebuilt_after_published_text_changes(search_state, monkeypatch):
    semantic._semantic_search("coal")
    old = semantic._lexical
    texts = ["Alice weaving cotton", "Alice weaving wool", "Bob weaving silk"]
    monkeypatch.setattr(semantic, "_embedding_texts", texts)
    semantic._semantic_search("silk")
    assert semantic._lexical is not old
    assert semantic._lexical.texts is texts
    assert semantic._lexical.scores("coal").sum() == 0


def test_passages_include_individual_citation_text_and_reference(monkeypatch):
    event = Event(
        type="OCCU",
        description="Cooper",
        citations=[Citation(source_id="@S1@", text="Made oak barrels in Cognac")],
    )
    monkeypatch.setattr(state, "individuals", {"@A@": Individual("@A@", "Alice", events=[event])})
    units = semantic._passage_units("@A@")
    assert "Made oak barrels in Cognac" in units[1][0]
    assert units[1][1]["source_ids"] == ["@S1@"]


def test_repeated_person_ids_and_provenance_survive_cache(search_state, monkeypatch, tmp_path):
    gedcom = tmp_path / "tree.ged"
    gedcom.write_text("0 HEAD\n")
    monkeypatch.setattr(state, "GEDCOM_FILE", gedcom)
    original = semantic._embedding_evidence
    semantic._save_cache()
    monkeypatch.setattr(semantic, "_embedding_evidence", [])
    assert semantic._load_cache()
    assert semantic._embedding_ids == ["@A@", "@A@", "@B@"]
    assert semantic._embedding_evidence == original


def test_failed_cache_save_preserves_previous_valid_file(search_state, monkeypatch, tmp_path):
    gedcom = tmp_path / "tree.ged"
    gedcom.write_text("0 HEAD\n")
    monkeypatch.setattr(state, "GEDCOM_FILE", gedcom)
    semantic._save_cache()
    path = semantic._get_cache_path()
    original = path.read_bytes()

    def fail(handle, **kwargs):
        handle.write(b"partial archive")
        raise OSError("disk full")

    monkeypatch.setattr(semantic.np, "savez_compressed", fail)
    semantic._save_cache()
    assert path.read_bytes() == original
    assert {p.name for p in tmp_path.iterdir()} == {gedcom.name, path.name}
