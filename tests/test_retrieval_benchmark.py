"""Check ranking metrics independently of expensive model inference."""

import math
from itertools import permutations

import pytest

from benchmarks.semantic_search.run import aggregate, metrics, random_expectation


def test_perfect_ranking():
    assert metrics(["a", "b", "c"], ["a", "b"]) == {
        "ndcg@10": 1.0,
        "recall@10": 1.0,
        "mrr@10": 1.0,
        "top1_accuracy": 1.0,
    }


def test_partial_ranking_penalizes_missing_and_late_hits():
    scores = metrics(["wrong", "a"], ["a", "b"])
    assert scores["recall@10"] == 0.5
    assert scores["mrr@10"] == 0.5
    assert scores["top1_accuracy"] == 0
    assert scores["ndcg@10"] == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)))


def test_cutoff_and_empty_results():
    assert all(value == 0 for value in metrics([], ["a"]).values())
    assert all(value == 0 for value in metrics(["x", "a"], ["a"], k=1).values())


@pytest.mark.parametrize("ranked,gold", [(["a", "a"], ["a"]), ([], []), ([], ["a", "a"])])
def test_invalid_judgments_and_duplicates_rejected(ranked, gold):
    with pytest.raises(ValueError):
        metrics(ranked, gold)


@pytest.mark.parametrize("relevant", [["a"], ["a", "b"], ["a", "b", "c"]])
@pytest.mark.parametrize("k", [1, 2, 10])
def test_random_expectation_matches_exhaustive_rankings(relevant, k):
    actual = aggregate(
        [{"metrics": metrics(list(order), relevant, k)} for order in permutations(["a", "b", "c"])]
    )
    assert random_expectation(3, len(relevant), k) == pytest.approx(actual)
