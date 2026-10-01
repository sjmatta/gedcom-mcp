"""Measure a real tree without recording private records, queries, or results.

Set GEDCOM_FILE, GEDCOM_CACHE_DIR and SEMANTIC_MODEL_CACHE to isolated paths.
Run twice against the same private cache to measure cold and warm startup.
"""

import argparse
import json
import os
import resource
import statistics
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(
        SEMANTIC_SEARCH_ENABLED="true", GIS_SEARCH_ENABLED="false", PHOENIX_ENABLED="false"
    )
    from gedcom_server import parsing, semantic, state

    state.GEDCOM_FILE = Path(os.environ["GEDCOM_FILE"])
    cache = semantic._get_cache_path()
    cache_existed = bool(cache and cache.exists())
    started = time.perf_counter()
    parsing.load_gedcom(derived=False)
    parse_seconds = time.perf_counter() - started
    started = time.perf_counter()
    semantic.build_embeddings()
    build_seconds = time.perf_counter() - started
    if semantic._embeddings is None:
        raise RuntimeError("No embeddings")
    queries = [
        "Who emigrated from Ireland to America?",
        "Who served in the army during the Second World War?",
        "Who worked as a coal miner?",
        "Who had twins?",
        "Who married in New York in 1900?",
    ]
    timings = []
    started = time.perf_counter()
    semantic._semantic_search(queries[0], max_results=10)
    first_query_seconds = time.perf_counter() - started
    for query in queries * 3:
        started = time.perf_counter()
        response = semantic._semantic_search(query, max_results=10)
        if response.get("warning") or response.get("error"):
            raise RuntimeError("Search failed or degraded")
        timings.append(time.perf_counter() - started)
    cgroup = Path("/sys/fs/cgroup")
    report = {
        "cache_existed": cache_existed,
        "people": len(state.individuals),
        "passages": len(semantic._embedding_ids),
        "embedding_bytes": semantic._embeddings.nbytes,
        "cache_bytes": cache.stat().st_size if cache else None,
        "parse_seconds": parse_seconds,
        "index_seconds": build_seconds,
        "first_query_seconds": first_query_seconds,
        "query_seconds": {"p50": statistics.median(timings), "p95": sorted(timings)[-1]},
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cgroup_peak_bytes": int((cgroup / "memory.peak").read_text()),
        "cgroup_memory_events": (cgroup / "memory.events").read_text(),
        "cpu_max": (cgroup / "cpu.max").read_text().strip(),
        "memory_max": int((cgroup / "memory.max").read_text()),
        "model": semantic.MODEL_NAME,
        "model_revision": semantic.MODEL_REVISION,
        "reranker": semantic.RERANKER_NAME,
        "reranker_revision": semantic.RERANKER_REVISION,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
