# Semantic search

Ask normal questions, such as “Who emigrated from Ireland to America?” or
“Who worked as a coal miner?” The search tool does not call an LLM to rewrite
queries. The calling assistant can try paraphrases or several smaller searches;
it should preserve the original wording, names, dates, negation, and relationships.

Search finds candidates, not verified answers. Check the returned evidence and
then use event, source, timeline, or relationship tools for exact constraints.
For example, “moved before marrying” requires checking recorded event dates.
The frozen challenge benchmark explicitly measures these remaining weaknesses.

## Retrieval

The sentence-transformers library remains the local inference runtime. The
default embedding model is now [BGE small English v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5),
with the model's retrieval instruction applied to queries. Each person's identity,
events, individual notes, family context, and citation text are indexed as separate
overlapping passages. Tokenizer offsets preserve evidence at the end of long notes.

Dense retrieval and a local BM25 inverted index contribute reciprocal-rank scores.
Both branches limit the passages per person so one long biography cannot consume
the candidate budget. The strongest passage is retained even when it matches only
through paraphrase. A second literal matching passage can supply another fact.

A [68M Ettin cross-encoder](https://huggingface.co/cross-encoder/ettin-reranker-68m-v1)
reranks a bounded set of people using query-centered excerpts and an explicit
record subject. Defaults rerank 20 people, in batches of four, with a 512-token
input limit. Models are pinned to immutable revisions and run locally on CPU.
No query or tree data is sent to an inference provider.

## Response and cache

Existing result fields remain available. Each result additionally includes
`evidence`, with passage text and applicable event, note, family, chunk, and source
references. `search_mode` identifies hybrid or hybrid-reranked results; `score_type`
identifies the score scale. `relevance_score` is an uncalibrated ranking signal;
reranker logits can exceed one or be negative. Do not reuse cosine thresholds.
If reranking fails, hybrid results include an explicit `warning`.

Content version 4 invalidates old biography caches. Cache validation checks the
GEDCOM hash, embedding model and revision, arrays, and passage metadata. Writes
use atomic replacement and compact UTF-8 arrays without pickle. Cache files
contain private tree excerpts and need the same protection as the GEDCOM.

Tree publication makes the prior search index unavailable until its refresh is
ready. Refreshes reuse vectors for identical person/passage text, encode changed
passages, recollect provenance, and publish only against the same tree revision.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SEMANTIC_SEARCH_ENABLED` | `false` | Enable indexing and the search tool |
| `SEMANTIC_DEVICE` | `cpu` | Explicit inference device |
| `SEMANTIC_MODEL_CACHE` | Library default | Persistent Hugging Face model cache |
| `GEDCOM_CACHE_DIR` | Beside GEDCOM | Search index directory |
| `SEMANTIC_RERANK_ENABLED` | `true` | Disable to use hybrid retrieval alone |
| `SEMANTIC_RERANK_CANDIDATES` | `20` | Rerank budget; at least requested results, capped at 200 |
| `SEMANTIC_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model override |
| `SEMANTIC_EMBEDDING_REVISION` | Pinned default | Revision for a custom embedding model |
| `SEMANTIC_RERANKER_MODEL` | `cross-encoder/ettin-reranker-68m-v1` | Reranker override |
| `SEMANTIC_RERANKER_REVISION` | Pinned default | Revision for a custom reranker |

## Preparing a full-tree index

A cold full-tree rebuild is a batch job. Prepare a validated index in a separate
cache before starting the production service with these defaults; changing the
embedding model or indexed content requires another full build. Give the isolated
build extra CPU, then serve the cached index at the regular production limits.
For a small tree edit, unchanged embeddings are reused.

With the intended GEDCOM and a separate writable cache selected:

```sh
GEDCOM_FILE=/path/to/tree.ged GEDCOM_CACHE_DIR=/path/to/new-cache \
SEMANTIC_MODEL_CACHE=/path/to/model-cache SEMANTIC_SEARCH_ENABLED=true \
GIS_SEARCH_ENABLED=false PHOENIX_ENABLED=false \
OMP_NUM_THREADS=6 TOKENIZERS_PARALLELISM=false \
.venv/bin/python -c 'from gedcom_server import state, parsing, semantic; state.configure(); parsing.load_gedcom(derived=False); semantic.build_embeddings()'
```

The prebuild must use the exact GEDCOM, code, and pinned embedding revision that
will serve the index. Keep production tree and cache mounts read-only during
testing; use an independent writable cache and leave production limits unchanged.

`benchmarks.semantic_search.resources` measures parsing, cache startup, first and
warm queries, process and cgroup memory, and OOM counters on Linux. It records
aggregate counts and timings without names, tree excerpts, queries, or results.
See [the benchmark report](benchmarks/semantic_search/README.md) for scores and
Rivendell measurements.
