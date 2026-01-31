"""Semantic search for GEDCOM genealogy data using sentence-transformers.

Provides natural language search across biographies, events, and notes.
Disabled by default; enable with SEMANTIC_SEARCH_ENABLED=true.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from . import state

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Configuration
MODEL_NAME = "all-MiniLM-L6-v2"

# Module-level state (set by build_embeddings)
_encoder = None
_embeddings: NDArray[np.float32] | None = None
_embedding_ids: list[str] = []
_embedding_texts: list[str] = []


def is_enabled() -> bool:
    """Check if semantic search is enabled via environment variable."""
    return os.getenv("SEMANTIC_SEARCH_ENABLED", "false").lower() == "true"


def _get_cache_path() -> Path | None:
    """Get path for embeddings cache file based on GEDCOM file location."""
    if state.GEDCOM_FILE is None:
        return None
    return state.GEDCOM_FILE.with_suffix(state.GEDCOM_FILE.suffix + ".embeddings.npz")


def _compute_gedcom_hash() -> str:
    """Compute SHA256 hash of the GEDCOM file for cache invalidation."""
    if state.GEDCOM_FILE is None:
        return ""
    sha256 = hashlib.sha256()
    with open(state.GEDCOM_FILE, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _load_cache() -> bool:
    """Load embeddings from cache if valid. Returns True on success."""
    global _embeddings, _embedding_ids, _embedding_texts

    cache_path = _get_cache_path()
    if cache_path is None or not cache_path.exists():
        return False

    try:
        with np.load(cache_path, allow_pickle=True) as data:
            cached_hash = str(data["gedcom_hash"])
            cached_model = str(data["model_name"])

            # Validate cache
            current_hash = _compute_gedcom_hash()
            if cached_hash != current_hash:
                logger.info("Cache invalidated: GEDCOM file changed")
                return False
            if cached_model != MODEL_NAME:
                logger.info("Cache invalidated: model changed")
                return False

            # Load embeddings
            _embeddings = data["embeddings"]
            _embedding_ids = list(data["ids"])
            _embedding_texts = list(data["texts"])
            return True
    except Exception as e:
        logger.warning(f"Failed to load embeddings cache: {e}")
        return False


def _save_cache() -> None:
    """Persist embeddings to cache file."""
    cache_path = _get_cache_path()
    if cache_path is None or _embeddings is None:
        return

    try:
        np.savez_compressed(
            cache_path,
            gedcom_hash=_compute_gedcom_hash(),
            model_name=MODEL_NAME,
            embeddings=_embeddings,
            ids=np.array(_embedding_ids, dtype=object),
            texts=np.array(_embedding_texts, dtype=object),
        )
        logger.info(f"Saved embeddings cache to {cache_path}")
    except Exception as e:
        logger.warning(f"Failed to save embeddings cache: {e}")


def _build_embedding_text(indi_id: str) -> str:
    """Build embeddable text from an individual's biography.

    Combines name, vital summary, family context, events, and notes
    into a single text block suitable for embedding.
    """
    indi = state.individuals.get(indi_id)
    if not indi:
        return ""

    parts: list[str] = []

    # Name and vital info
    parts.append(indi.full_name())

    # Vital summary
    vital_parts = []
    if indi.birth_date or indi.birth_place:
        birth_info = "Born"
        if indi.birth_date:
            birth_info += f" {indi.birth_date}"
        if indi.birth_place:
            birth_info += f" in {indi.birth_place}"
        vital_parts.append(birth_info)
    if indi.death_date or indi.death_place:
        death_info = "Died"
        if indi.death_date:
            death_info += f" {indi.death_date}"
        if indi.death_place:
            death_info += f" in {indi.death_place}"
        vital_parts.append(death_info)
    if vital_parts:
        parts.append(". ".join(vital_parts) + ".")

    # Parents context
    if indi.family_as_child:
        fam = state.families.get(indi.family_as_child)
        if fam:
            parent_names = []
            if fam.husband_id and fam.husband_id in state.individuals:
                parent_names.append(state.individuals[fam.husband_id].full_name())
            if fam.wife_id and fam.wife_id in state.individuals:
                parent_names.append(state.individuals[fam.wife_id].full_name())
            if parent_names:
                parts.append(f"Parents: {', '.join(parent_names)}.")

    # Spouse context
    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            spouse_id = fam.wife_id if fam.husband_id == indi_id else fam.husband_id
            if spouse_id and spouse_id in state.individuals:
                spouse_name = state.individuals[spouse_id].full_name()
                marriage_info = f"Married {spouse_name}"
                if fam.marriage_date:
                    marriage_info += f" {fam.marriage_date}"
                if fam.marriage_place:
                    marriage_info += f" in {fam.marriage_place}"
                parts.append(marriage_info + ".")

    # Events with descriptions and notes
    for event in indi.events:
        event_parts = []
        event_type = event.type
        if event.description:
            event_parts.append(f"{event_type}: {event.description}")
        else:
            event_parts.append(event_type)
        if event.date:
            event_parts.append(event.date)
        if event.place:
            event_parts.append(f"in {event.place}")
        parts.append(" ".join(event_parts) + ".")

        # Event-level notes
        for note in event.notes:
            parts.append(note)

    # Individual-level notes (obituaries, stories, etc.)
    for note in indi.notes:
        parts.append(note)

    return " ".join(parts)


def build_embeddings() -> None:
    """Build or load embeddings for all individuals.

    Called at startup after GEDCOM parsing. If SEMANTIC_SEARCH_ENABLED is false,
    this function returns immediately without building embeddings.

    Cache strategy:
    - First checks for valid cache at {gedcom_file}.embeddings.npz
    - Cache invalidated if GEDCOM file hash or model name changes
    - If no valid cache, builds embeddings and saves to cache
    """
    global _encoder, _embeddings, _embedding_ids, _embedding_texts

    if not is_enabled():
        logger.debug("Semantic search disabled")
        return

    # Try to load from cache first
    if _load_cache():
        logger.info(f"Loaded {len(_embedding_ids)} embeddings from cache")
        return

    # Import sentence-transformers only when needed (lazy load)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning(
            "sentence-transformers not installed. Semantic search disabled. "
            "Install with: pip install sentence-transformers"
        )
        return

    logger.info("Building embeddings (first run or GEDCOM changed)...")

    # Build texts for all individuals
    texts: list[str] = []
    ids: list[str] = []
    for indi_id in state.individuals:
        text = _build_embedding_text(indi_id)
        if text.strip():
            texts.append(text)
            ids.append(indi_id)

    if not texts:
        logger.warning("No individuals to embed")
        return

    # Load model and encode
    _encoder = SentenceTransformer(MODEL_NAME)
    _embeddings = _encoder.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    _embedding_ids = ids
    _embedding_texts = texts

    logger.info(f"Built {len(_embedding_ids)} embeddings")

    # Save to cache
    _save_cache()


def _semantic_search(query: str, max_results: int = 20) -> dict:
    """Perform semantic search over individual embeddings.

    Args:
        query: Natural language search query
        max_results: Maximum number of results (default 20, max 100)

    Returns:
        Dictionary with query, result_count, and results list
    """
    global _encoder

    if not is_enabled():
        return {"error": "Semantic search not enabled", "results": []}

    if _embeddings is None or len(_embedding_ids) == 0:
        return {"error": "Embeddings not built", "results": []}

    # Clamp max_results
    max_results = min(max(1, max_results), 100)

    # Lazy load encoder if needed (for queries after server restart without rebuild)
    if _encoder is None:
        try:
            from sentence_transformers import SentenceTransformer

            _encoder = SentenceTransformer(MODEL_NAME)
        except ImportError:
            return {"error": "sentence-transformers not installed", "results": []}

    # Encode query
    query_embedding = _encoder.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0]

    # Compute similarities (dot product of normalized vectors = cosine similarity)
    similarities = np.dot(_embeddings, query_embedding)

    # Get top-k indices
    top_indices = np.argsort(similarities)[::-1][:max_results]

    # Build results
    results: list[dict] = []
    for idx in top_indices:
        indi_id = _embedding_ids[idx]
        indi = state.individuals.get(indi_id)
        if not indi:
            continue

        # Create snippet from embedding text (truncated)
        full_text = _embedding_texts[idx]
        snippet = full_text[:300] + "..." if len(full_text) > 300 else full_text

        results.append(
            {
                "individual_id": indi_id,
                "name": indi.full_name(),
                "birth_date": indi.birth_date,
                "death_date": indi.death_date,
                "relevance_score": round(float(similarities[idx]), 3),
                "snippet": snippet,
            }
        )

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }
