"""Local passage splitting and BM25 retrieval; no database or network services."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

import numpy as np

# Keep negation and numbers. Drop only common grammatical/query scaffolding.
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "who",
        "whose",
        "which",
        "find",
        "people",
        "person",
        "individuals",
        "was",
        "were",
        "is",
        "are",
        "be",
        "been",
        "of",
        "to",
        "in",
        "at",
        "on",
        "for",
        "from",
        "and",
        "or",
        "as",
        "with",
        "that",
        "their",
        "his",
        "her",
        "he",
        "she",
        "it",
        "they",
        "what",
        "where",
        "how",
        "did",
        "does",
        "do",
        "had",
        "has",
        "have",
    ]
)


def terms(text: str) -> list[str]:
    return [word for word in re.findall(r"[^\W_]+", text.casefold()) if word not in STOP_WORDS]


def matching_snippet(text: str, query: str, limit: int = 600) -> str:
    """Center a bounded excerpt on the greatest number of distinct query terms."""
    if len(text) <= limit:
        return text
    query_terms = set(terms(query))
    starts = {0}
    for match in re.finditer(r"[^\W_]+", text):
        if match.group().casefold() in query_terms:
            starts.add(max(0, min(len(text) - limit, match.start() - limit // 3)))
    start = max(sorted(starts), key=lambda i: len(query_terms & set(terms(text[i : i + limit]))))
    end = start + limit
    return ("..." if start else "") + text[start:end] + ("..." if end < len(text) else "")


def split_passages(text: str, prefix: str, encoder) -> list[str]:
    """Slice original text at tokenizer offsets, retaining overlap and name context.

    Real encoders use exact token offsets, so every token is covered without
    silently truncating long notes. The whitespace fallback supports minimal
    encoders in tests; production requires a fast offset-capable tokenizer.
    """
    tokenizer = getattr(encoder, "tokenizer", None)
    if tokenizer is None:
        words = text.split()
        return [prefix + " ".join(words[i : i + 160]) for i in range(0, len(words), 128)]
    prefix_tokens = len(tokenizer.encode(prefix, add_special_tokens=False))
    # Reserve room for model instructions and special tokens. Smaller passages
    # also fit the reranker together with the query and a second evidence unit.
    budget = min(192, encoder.max_seq_length - prefix_tokens - 32)
    if budget < 32:
        raise ValueError("Name context leaves insufficient model input space")
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)[
        "offset_mapping"
    ]
    if not offsets:
        return []
    result = []
    step = budget - min(32, budget // 4)
    for start in range(0, len(offsets), step):
        end = min(start + budget, len(offsets))
        result.append(prefix + text[offsets[start][0] : offsets[end - 1][1]])
        if end == len(offsets):
            break
    return result


class BM25:
    """An inverted index built once per published passage-text list."""

    def __init__(self, texts: list[str]):
        self.texts = texts
        lengths = []
        postings = defaultdict(list)
        for index, text in enumerate(texts):
            counts = Counter(terms(text))
            lengths.append(sum(counts.values()))
            for word, count in counts.items():
                postings[word].append((index, count))
        self.lengths = np.asarray(lengths, dtype=np.float32)
        self.average = max(1.0, float(self.lengths.mean()))
        self.postings = {
            word: (np.asarray([i for i, _ in rows]), np.asarray([n for _, n in rows]))
            for word, rows in postings.items()
        }

    def scores(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.texts), dtype=np.float32)
        for word in set(terms(query)):
            posting = self.postings.get(word)
            if posting is None:
                continue
            indices, frequency = posting
            idf = math.log1p((len(self.texts) - len(indices) + 0.5) / (len(indices) + 0.5))
            normalization = 1.2 * (0.25 + 0.75 * self.lengths[indices] / self.average)
            scores[indices] += idf * frequency * 2.2 / (frequency + normalization)
        return scores


def top_indices(scores: np.ndarray, count: int) -> list[int]:
    """Bound selection cost on large passage indexes, with deterministic ties."""
    count = min(count, len(scores))
    if count <= 0:
        return []
    # Partition gives the cutoff; include boundary ties before sorting by index.
    cutoff = np.partition(scores, len(scores) - count)[len(scores) - count]
    candidates = np.flatnonzero(scores >= cutoff)
    order = np.lexsort((candidates, -scores[candidates]))[:count]
    return candidates[order].tolist()


def diverse_top_indices(scores: np.ndarray, ids: list[str], count: int) -> list[int]:
    """Prevent one long biography from consuming a branch's candidate budget."""
    fetch = min(len(scores), count * 4)
    while True:
        selected: list[int] = []
        seen: Counter[str] = Counter()
        for index in top_indices(scores, fetch):
            person = ids[index]
            if seen[person] < 2:
                seen[person] += 1
                selected.append(index)
            if len(selected) == count:
                return selected
        if fetch == len(scores):
            return selected
        fetch = min(len(scores), fetch * 2)
