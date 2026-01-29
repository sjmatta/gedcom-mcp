"""Source-related functions for querying genealogy data."""

from . import state
from .core import _normalize_lookup_id


def _get_sources(max_results: int = 100) -> list[dict]:
    """Get all sources in the tree."""
    results = []
    for source in state.sources.values():
        results.append(source.to_summary())
        if len(results) >= max_results:
            break
    return results


def _get_source(source_id: str) -> dict | None:
    """Get a source by its ID."""
    lookup_id = _normalize_lookup_id(source_id)
    source = state.sources.get(lookup_id)
    return source.to_dict() if source else None


def _search_sources(query: str, max_results: int = 50) -> list[dict]:
    """Search sources by title or author."""
    query_lower = query.lower()
    results = []

    for source in state.sources.values():
        title_match = source.title and query_lower in source.title.lower()
        author_match = source.author and query_lower in source.author.lower()

        if title_match or author_match:
            results.append(source.to_summary())
            if len(results) >= max_results:
                break

    return results
