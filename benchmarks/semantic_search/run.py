"""Run the real semantic search implementation against frozen relevance judgments."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).parent


def metrics(ranked: list[str], relevant: list[str], k: int = 10) -> dict[str, float]:
    """Binary relevance; missing relevant people contribute zero gain."""
    if not relevant or len(set(relevant)) != len(relevant):
        raise ValueError("Each case needs unique, nonempty relevance judgments")
    if len(set(ranked)) != len(ranked):
        raise ValueError("Search returned duplicate individuals")
    gold = set(relevant)
    hits = [i for i, person in enumerate(ranked[:k], start=1) if person in gold]
    dcg = sum(1 / math.log2(i + 1) for i in hits)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(gold)) + 1))
    return {
        f"ndcg@{k}": dcg / ideal,
        f"recall@{k}": len(hits) / len(gold),
        f"mrr@{k}": 1 / hits[0] if hits else 0.0,
        "top1_accuracy": float(bool(ranked) and ranked[0] in gold),
    }


def aggregate(rows: list[dict]) -> dict:
    return {key: statistics.mean(row["metrics"][key] for row in rows) for key in rows[0]["metrics"]}


def random_expectation(corpus_size: int, relevant_count: int, k: int = 10) -> dict[str, float]:
    """Exact expected metrics for a uniformly shuffled corpus, without simulation."""
    if not 0 < relevant_count <= corpus_size or k < 1:
        raise ValueError("Invalid corpus size, relevance count, or cutoff")
    cutoff = min(k, corpus_size)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, relevant_count) + 1))
    expected_dcg = (relevant_count / corpus_size) * sum(
        1 / math.log2(i + 1) for i in range(1, cutoff + 1)
    )
    no_hit, expected_mrr = 1.0, 0.0
    for rank in range(1, cutoff + 1):
        remaining = corpus_size - rank + 1
        hit_probability = min(1.0, relevant_count / remaining)
        expected_mrr += no_hit * hit_probability / rank
        no_hit *= 1 - hit_probability
    return {
        f"ndcg@{k}": expected_dcg / ideal,
        f"recall@{k}": cutoff / corpus_size,
        f"mrr@{k}": expected_mrr,
        "top1_accuracy": relevant_count / corpus_size,
    }


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=ROOT / "suite.json")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    records, cases = suite["records"], suite["cases"]
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)) or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate record or case IDs")
    if not cases:
        raise ValueError("Empty benchmark")
    for case in cases:
        if not case["query"].strip() or not set(case["relevant"]) <= set(ids):
            raise ValueError(f"Invalid query or gold IDs: {case['id']}")
        metrics([], case["relevant"])
        negatives = case.get("hard_negative_ids", [])
        if (
            len(set(negatives)) != len(negatives)
            or not set(negatives) <= set(ids)
            or set(negatives) & set(case["relevant"])
        ):
            raise ValueError(f"Invalid hard negatives: {case['id']}")

    # Override optional integrations before importing the application. Never load
    # the private tree, write to its cache, or start background GIS/telemetry work.
    os.environ.update(
        SEMANTIC_SEARCH_ENABLED="true", GIS_SEARCH_ENABLED="false", PHOENIX_ENABLED="false"
    )
    from gedcom_server import parsing, retrieval, semantic, state

    semantic_source_hash = hashlib.sha256(Path(semantic.__file__).read_bytes()).hexdigest()
    runner_source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    retrieval_source_hash = hashlib.sha256(Path(retrieval.__file__).read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory(prefix="gedcom-retrieval-") as directory:
        gedcom = Path(directory) / "benchmark.ged"
        lines = ["0 HEAD", "1 SOUR RetrievalBenchmark", "1 GEDC", "2 VERS 5.5.1", "1 CHAR UTF-8"]
        for record in records:
            lines.extend([f"0 {record['id']} INDI", *record["gedcom"]])
        lines.append("0 TRLR")
        gedcom.write_text("\n".join(lines) + "\n")
        state.GEDCOM_FILE = gedcom
        os.environ["GEDCOM_CACHE_DIR"] = directory
        parsing.load_gedcom(derived=False)
        if set(state.individuals) != set(ids):
            raise ValueError("Parsed corpus does not match suite")
        started = time.perf_counter()
        semantic.build_embeddings()
        build_seconds = time.perf_counter() - started
        if semantic._embeddings is None:
            raise RuntimeError("Real embeddings were not built; no mocked baseline allowed")
        semantic._semantic_search(cases[0]["query"], max_results=10)  # Warm up inference.
        rows, latencies = [], []
        for case in cases:
            timings, rankings = [], []
            for _ in range(args.repeats):
                started = time.perf_counter()
                response = semantic._semantic_search(case["query"], max_results=10)
                timings.append((time.perf_counter() - started) * 1000)
                if "error" in response:
                    raise RuntimeError(response["error"])
                if "warning" in response:
                    raise RuntimeError(response["warning"])
                ranked = [result["individual_id"] for result in response["results"]]
                if not set(ranked) <= set(ids):
                    raise ValueError("Search returned unknown IDs")
                rankings.append(ranked)
            if any(ranking != rankings[0] for ranking in rankings):
                raise RuntimeError(f"Unstable ranking: {case['id']}")
            latencies.extend(timings)
            rows.append(
                {
                    **case,
                    "ranked_ids": rankings[0],
                    "metrics": {
                        **metrics(rankings[0], case["relevant"], k=5),
                        **metrics(rankings[0], case["relevant"]),
                    },
                    "latency_ms_median": statistics.median(timings),
                    "search_mode": response.get("search_mode", "dense"),
                }
            )
        groups = defaultdict(list)
        for row in rows:
            groups[row["category"]].append(row)
        revision = os.getenv("BENCHMARK_GIT_REVISION")
        if revision is None:
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
        model_revision = getattr(
            semantic._encoder[0].auto_model.config, "_commit_hash", None
        ) or getattr(semantic, "MODEL_REVISION", None)
        report = {
            "run_at": datetime.now(UTC).isoformat(),
            "suite_version": suite["version"],
            "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
            "corpus_sha256": hashlib.sha256(gedcom.read_bytes()).hexdigest(),
            "git_revision": revision,
            "semantic_source_sha256": semantic_source_hash,
            "runner_source_sha256": runner_source_hash,
            "retrieval_source_sha256": retrieval_source_hash,
            "model": semantic.MODEL_NAME,
            "model_revision": model_revision,
            "configured_model_revision": getattr(semantic, "MODEL_REVISION", None),
            "reranker_model": getattr(semantic, "RERANKER_NAME", None),
            "reranker_revision": getattr(semantic, "RERANKER_REVISION", None),
            "rerank_enabled": os.getenv("SEMANTIC_RERANK_ENABLED", "true").lower() == "true",
            "search_modes": sorted({row["search_mode"] for row in rows}),
            "content_version": semantic.CONTENT_VERSION,
            "embedding_shape": list(semantic._embeddings.shape),
            "device": str(semantic._encoder.device),
            "max_sequence_length": semantic._encoder.max_seq_length,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                **{name: version(name) for name in ("sentence-transformers", "torch", "numpy")},
                "omp_num_threads": os.getenv("OMP_NUM_THREADS"),
                "rerank_candidates": os.getenv("SEMANTIC_RERANK_CANDIDATES", "20"),
                "cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip()
                if Path("/sys/fs/cgroup/cpu.max").exists()
                else None,
                "memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip()
                if Path("/sys/fs/cgroup/memory.max").exists()
                else None,
            },
            "record_count": len(ids),
            "query_count": len(cases),
            "repeats": args.repeats,
            "build_seconds": build_seconds,
            "latency_ms": {"p50": statistics.median(latencies), "p95": percentile(latencies, 0.95)},
            "overall": aggregate(rows),
            "random_ranking_expectation": aggregate(
                [
                    {
                        "metrics": {
                            **random_expectation(len(ids), len(case["relevant"]), k=5),
                            **random_expectation(len(ids), len(case["relevant"])),
                        }
                    }
                    for case in cases
                ]
            ),
            "categories": {
                key: {"query_count": len(group), **aggregate(group)}
                for key, group in groups.items()
            },
            "cases": rows,
        }
        if all(case.get("hard_negative_ids") for case in cases):
            report["contrast_set_random_top1"] = statistics.mean(
                len(case["relevant"]) / (len(case["relevant"]) + len(case["hard_negative_ids"]))
                for case in cases
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: report[key] for key in ("overall", "categories", "latency_ms", "build_seconds")},
            indent=2,
        )
    )
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
