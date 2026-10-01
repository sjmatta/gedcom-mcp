# Semantic search benchmark

This is a fixed, synthetic person-retrieval evaluation of the real
`gedcom_server.semantic._semantic_search` implementation. No embeddings or search
results are mocked. It leaves the production retrieval implementation unchanged.

## Run

From the repository root, using the project environment:

```sh
.venv/bin/python -m benchmarks.semantic_search.run --output /tmp/retrieval-current.json
```

If the model is already cached, avoid Hugging Face update checks:

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m benchmarks.semantic_search.run --output /tmp/retrieval-current.json
```

The runner creates a temporary GEDCOM and fresh embedding cache, invokes the
production parser and embedding builder, warms up inference, then runs each query
three times. It fails if embeddings are unavailable or rankings differ between
repeats. GIS and telemetry are disabled; the private family tree is never loaded.

## Frozen suite and scoring

`suite.json` contains 32 synthetic people and 30 queries, with explicit exhaustive
binary relevance judgments and short explanations. Categories cover occupations,
places, emigration dates/destinations, military service, life events, exact-name
disambiguation, misleading matches, and evidence late in long notes. Those notes
deliberately exceed MiniLM's input limit. All queries have at least one answer.
Gold judgments were authored from the fixture facts before running retrieval.

The headline score is **mean nDCG@10**: relevant people earn more credit near the
top, and the ideal ranking scores 1. Also reported:

- Recall@10: fraction of all relevant people found in the first ten results.
- MRR@10: reciprocal rank of the first relevant person, zero if absent.
- Top-1 accuracy: fraction of queries whose first result is relevant.
- The current runner additionally reports nDCG, recall, and MRR at cutoff 5,
  and exact expected metrics for uniformly random corpus rankings.
- Warm query latency p50/p95 and fresh-index build time (including model load).

Scores are averaged equally across queries, rather than across categories.
The JSON includes per-query rankings, category scores, suite/corpus/source hashes,
Git revision, model revision, library versions, device, and sequence limit. Change
the suite version when editing facts or labels; compare scores only on the same
suite hash. Keep `baseline.json` as the original baseline; write later runs to
separate files. Metric unit tests run with the regular pytest suite.

## Initial baseline

The current `all-MiniLM-L6-v2` implementation scores:

| Metric | Baseline |
|---|---:|
| nDCG@10 | 0.7875 |
| Recall@10 | 86.67% |
| MRR@10 | 0.7694 |
| Top-1 accuracy | 70.00% (21/30) |
| Long-note recall@10 | 0.00% (0/4 queries) |

See `baseline.json` for measured timing and provenance. All four long-note queries
miss their relevant person entirely in the top ten. This gives us an explicit
target for passage indexing, alongside the other categories as regression checks.

This is a small diagnostic development suite, not an estimate of production
accuracy. Ten results among 32 people is a generous cutoff. It does not measure
abstention, evidence-snippet quality, graph/ancestry constraints, family-event
retrieval, or performance at the private tree's scale. Related queries share
facts, so the 30 cases are not 30 independent statistical samples. Before claiming
broad improvement, add separately judged held-out queries and evaluate on a
representative larger corpus. Latency measured here is local and does not establish
Rivendell deployment latency.

## Challenge suite

`challenge.json` is a separate version-2 suite with **200 people and 40 queries**.
Each manually authored scenario has five competing biographies. Most have one
correct person and four explicitly labeled hard negatives; one has two correct
people and three negatives. All 200 people are searched on every query; scenario
groups and gold judgments are never passed to retrieval. Labels were written
before running the model. The version-1 suite and baseline remain unchanged.

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m benchmarks.semantic_search.run \
  --suite benchmarks/semantic_search/challenge.json \
  --output /tmp/retrieval-challenge-current.json
```

There are five queries in each category:

- Temporal order: the same events in the wrong sequence.
- Conjunction: a person must satisfy several facts together.
- Subject attribution: own achievements versus a relative's, customer’s, or subject’s.
- Negation: declined versus accepted, acquitted versus convicted, intended versus actual.
- Occupational paraphrases: cooper, cobbler, midwife, postman, lighthouse keeper.
- Dates and numbers: ages, uninterrupted residence, exact child counts, widowhood.
- Identity: namesakes distinguished by aliases, maiden names, dates, and places.
- Late evidence: ordinary narrative context before the only relevant passage.

| Metric | Basic suite | Challenge suite |
|---|---:|---:|
| nDCG@10 | 0.7875 | 0.6249 |
| Recall@10 | 86.67% | 87.50% |
| MRR@10 | 0.7694 | 0.5375 |
| Top-1 accuracy | 70.00% | 30.00% (12/40) |

The challenge's cutoff-5 scores equal its cutoff-10 scores: every successful
query finds all relevant people in the first five, while all five late-evidence
queries fail entirely. Top-1 accuracy is only 20% each for conjunction, subject
attribution, and negation. These cases reveal ranking errors even when recall
looks healthy. The model tends to retrieve the correct topic without reliably
distinguishing the actual matching biography from close alternatives.

`challenge-baseline.json` preserves full rankings, labels, provenance, category
scores, random-ranking expectations, and timing. A uniformly random shuffle of
all 200 people expects 5% recall@10, but that is a weak reference: the corpus has
40 distinct topic clusters. Choosing randomly within each five-person scenario
expects **20.5% top-1 accuracy**, versus the model's 30%. This contrast reference
is stored separately; it assumes the right topic has already been found.

The challenge is still a synthetic development set, deliberately authored after
seeing the basic suite's limitations. It is not a held-out estimate of ordinary
user-query accuracy, and the two suite scores should not be interpreted as a
before/after regression. Date arithmetic and multiple conditions test person
relevance even when answering fully may need structured reasoning. Neither suite
tests no-answer queries or calibrated abstention. Use the challenge to measure
improvements and the basic suite to catch regressions, always comparing each
against its own frozen baseline on the same suite hash.
