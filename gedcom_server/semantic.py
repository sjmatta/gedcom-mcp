"""Semantic search for GEDCOM genealogy data using sentence-transformers.

Provides natural language search across biographies, events, and notes.
Disabled by default; enable with SEMANTIC_SEARCH_ENABLED=true.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from . import state
from .retrieval import BM25, diverse_top_indices, matching_snippet, split_passages

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Configuration
MODEL_NAME = os.getenv("SEMANTIC_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
MODEL_REVISION = os.getenv("SEMANTIC_EMBEDDING_REVISION") or {
    "BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    "all-MiniLM-L6-v2": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
}.get(MODEL_NAME)
RERANKER_NAME = os.getenv("SEMANTIC_RERANKER_MODEL", "cross-encoder/ettin-reranker-68m-v1")
RERANKER_REVISION = os.getenv("SEMANTIC_RERANKER_REVISION") or {
    "cross-encoder/ettin-reranker-68m-v1": "d166fa88ddde3c42bc3ee92f7df476d941c8204a",
    "cross-encoder/ettin-reranker-150m-v1": "025501c4e0f9bbeb4c5b198318e0089ff061cc14",
    "cross-encoder/ms-marco-MiniLM-L6-v2": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
    "Qwen/Qwen3-Reranker-0.6B": "e61197ed45024b0ed8a2d74b80b4d909f1255473",
}.get(RERANKER_NAME)
# Bump when parsing or embedding-text construction changes.
CONTENT_VERSION = 4

# Module-level state (set by build_embeddings)
_encoder = None
_embeddings: NDArray[np.float32] | None = None
_embedding_ids: list[str] = []
_embedding_texts: list[str] = []
_embedding_evidence: list[dict] = []
_lexical: BM25 | None = None
_reranker = None
_previous_index = None


def _remember_index() -> None:
    """Retain vectors for rebuilding; they are never exposed as current results."""
    global _previous_index
    _previous_index = (_embedding_ids, _embedding_texts, _embeddings)


def is_enabled() -> bool:
    """Check if semantic search is enabled via environment variable."""
    return os.getenv("SEMANTIC_SEARCH_ENABLED", "false").lower() == "true"


def _get_cache_path() -> Path | None:
    """Get path for embeddings cache file based on GEDCOM file location."""
    if state.GEDCOM_FILE is None:
        return None
    directory = os.getenv("GEDCOM_CACHE_DIR")
    if directory:
        return Path(directory) / "tree.embeddings.npz"
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
    global _embeddings, _embedding_ids, _embedding_texts, _embedding_evidence

    cache_path = _get_cache_path()
    if cache_path is None or not cache_path.exists():
        return False

    try:
        with np.load(cache_path, allow_pickle=False) as data:
            if "content_version" not in data or int(data["content_version"]) != CONTENT_VERSION:
                logger.info("Cache invalidated: indexed content changed")
                return False
            cached_hash = str(data["gedcom_hash"])
            cached_model = str(data["model_name"])

            # Validate cache
            current_hash = _compute_gedcom_hash()
            if cached_hash != current_hash:
                logger.info("Cache invalidated: GEDCOM file changed")
                return False
            if cached_model != MODEL_NAME or str(data.get("model_revision", "")) != (
                MODEL_REVISION or ""
            ):
                logger.info("Cache invalidated: model changed")
                return False

            # Validate all arrays before publishing any cache state.
            embeddings = data["embeddings"]
            ids = data["ids"]
            if "texts_utf8" in data:
                encoded = data["texts_utf8"]
                offsets = data["text_offsets"]
                if (
                    encoded.ndim != 1
                    or encoded.dtype != np.uint8
                    or offsets.ndim != 1
                    or offsets.dtype != np.int64
                    or len(offsets) != len(ids) + 1
                    or offsets[0] != 0
                    or offsets[-1] != len(encoded)
                    or np.any(offsets[1:] < offsets[:-1])
                ):
                    return False
                raw = encoded.tobytes()
                texts = [
                    raw[start:end].decode("utf-8")
                    for start, end in zip(offsets[:-1], offsets[1:], strict=True)
                ]
            else:
                # Read safe caches from the previous Unicode-array format.
                legacy_texts = data["texts"]
                if legacy_texts.ndim != 1 or legacy_texts.dtype.kind != "U":
                    return False
                texts = legacy_texts.tolist()
            if (
                embeddings.ndim != 2
                or embeddings.shape[1] == 0
                or not np.issubdtype(embeddings.dtype, np.floating)
                or not np.isfinite(embeddings).all()
                or ids.ndim != 1
                or ids.dtype.kind != "U"
                or len(ids) != len(texts)
                or len(ids) != len(embeddings)
                or any(not person.strip() for person in ids)
            ):
                logger.warning("Invalid embedding cache arrays; rebuilding")
                return False
            evidence: list[dict] = [{} for _ in texts]
            if "evidence_utf8" in data:
                encoded_evidence = data["evidence_utf8"]
                if encoded_evidence.ndim != 1 or encoded_evidence.dtype != np.uint8:
                    return False
                evidence = json.loads(encoded_evidence.tobytes().decode("utf-8"))
                if (
                    not isinstance(evidence, list)
                    or len(evidence) != len(texts)
                    or any(not isinstance(item, dict) for item in evidence)
                ):
                    return False
            _embedding_evidence = evidence
            _embeddings = embeddings
            _embedding_ids = ids.tolist()
            _embedding_texts = texts
            return True
    except Exception as e:
        logger.warning(f"Failed to load embeddings cache: {e}")
        return False


def _save_cache() -> None:
    """Persist embeddings to cache file."""
    cache_path = _get_cache_path()
    if cache_path is None or _embeddings is None:
        return

    temporary: Path | None = None
    try:
        # Fixed-width Unicode arrays multiply the longest biography by the tree
        # size. UTF-8 plus offsets instead uses space proportional to actual text.
        chunks = [text.encode("utf-8") for text in _embedding_texts]
        offsets = np.zeros(len(chunks) + 1, dtype=np.int64)
        offsets[1:] = np.cumsum([len(chunk) for chunk in chunks], dtype=np.int64)
        arrays: dict = {
            "gedcom_hash": _compute_gedcom_hash(),
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION or "",
            "content_version": CONTENT_VERSION,
            "embeddings": _embeddings,
            "ids": np.array(_embedding_ids, dtype=str),
            "texts_utf8": np.frombuffer(b"".join(chunks), dtype=np.uint8),
            "text_offsets": offsets,
            "evidence_utf8": np.frombuffer(
                json.dumps(
                    _embedding_evidence
                    if len(_embedding_evidence) == len(_embedding_texts)
                    else [{} for _ in _embedding_texts],
                    ensure_ascii=False,
                ).encode("utf-8"),
                dtype=np.uint8,
            ),
        }
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent, suffix=".npz", delete=False
        ) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, **arrays)
        os.replace(temporary, cache_path)
        logger.info(f"Saved embeddings cache to {cache_path}")
    except Exception as e:
        logger.warning(f"Failed to save embeddings cache: {e}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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

    for family_id in dict.fromkeys(indi.families_as_spouse):
        family = state.families.get(family_id)
        if family:
            for event in family.events:
                parts.append(
                    " ".join(
                        str(value)
                        for value in (event.type, event.date, event.place, event.description)
                        if value
                    )
                )
                parts.extend(event.notes)
                parts.extend(citation.text for citation in event.citations if citation.text)
    return " ".join(parts)


def _identity_text(indi_id: str) -> str:
    indi = state.individuals[indi_id]
    parts = [indi.full_name()]
    for label, date, place in (
        ("Born", indi.birth_date, indi.birth_place),
        ("Died", indi.death_date, indi.death_place),
    ):
        if date or place:
            parts.append(" ".join(v for v in (label, date, f"in {place}" if place else None) if v))
    return ". ".join(parts) + ". "


def _passage_units(indi_id: str) -> list[tuple[str, dict]]:
    """Keep event and note boundaries, and retain references to source records."""
    indi = state.individuals[indi_id]
    units: list[tuple[str, dict]] = [(_identity_text(indi_id), {"kind": "identity"})]
    if indi.family_as_child:
        family = state.families.get(indi.family_as_child)
        if family:
            names = [
                state.individuals[key].full_name()
                for key in (family.husband_id, family.wife_id)
                if key in state.individuals
            ]
            if names:
                units.append(
                    ("Parents: " + ", ".join(names), {"kind": "parents", "family_id": family.id})
                )
    for family_id in dict.fromkeys(indi.families_as_spouse):
        family = state.families.get(family_id)
        if not family:
            continue
        spouse_id = family.wife_id if family.husband_id == indi_id else family.husband_id
        if spouse_id in state.individuals:
            units.append(
                (
                    " ".join(
                        str(v)
                        for v in (
                            "Married",
                            state.individuals[spouse_id].full_name(),
                            family.marriage_date,
                            family.marriage_place,
                        )
                        if v
                    ),
                    {"kind": "marriage", "family_id": family_id},
                )
            )
    labels = {
        "OCCU": "Occupation",
        "BIRT": "Birth",
        "DEAT": "Death",
        "EMIG": "Emigration",
        "IMMI": "Immigration",
        "RESI": "Residence",
        "BURI": "Burial",
        "MARR": "Marriage",
    }

    def event_unit(event, index, family_id=None):
        text = " ".join(
            str(v)
            for v in (
                f"{labels.get(event.type, event.type)} ({event.type}):",
                event.description,
                event.date,
                event.place,
                *event.notes,
                *(citation.text for citation in event.citations if citation.text),
            )
            if v
        )
        metadata = {
            "kind": "family_event" if family_id else "event",
            "event_index": index,
            "event_type": event.type,
            "source_ids": [c.source_id for c in event.citations],
        }
        if family_id:
            metadata["family_id"] = family_id
        units.append((text, metadata))

    for index, event in enumerate(indi.events):
        event_unit(event, index)
    for index, note in enumerate(indi.notes):
        units.append((note, {"kind": "note", "note_index": index}))
    for family_id in dict.fromkeys(indi.families_as_spouse):
        family = state.families.get(family_id)
        if family:
            for index, event in enumerate(family.events):
                event_unit(event, index, family_id)
    return units


def _collect_passages(encoder) -> tuple[list[str], list[str], list[dict]]:
    ids, texts, evidence = [], [], []
    for indi_id in state.individuals:
        prefix = _identity_text(indi_id)
        seen = set()
        for text, metadata in _passage_units(indi_id):
            for chunk, passage in enumerate(
                split_passages(text, "" if metadata["kind"] == "identity" else prefix, encoder)
            ):
                if passage not in seen:
                    ids.append(indi_id)
                    texts.append(passage)
                    evidence.append({**metadata, "chunk": chunk})
                    seen.add(passage)
    return ids, texts, evidence


def _new_encoder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
        device=os.getenv("SEMANTIC_DEVICE", "cpu"),
        cache_folder=os.getenv("SEMANTIC_MODEL_CACHE"),
    )


def _encode_documents(encoder, texts: list[str], *, progress: bool):
    encode = getattr(encoder, "encode_document", encoder.encode)
    return encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=progress,
        convert_to_numpy=True,
        batch_size=16,
    )


def _encode_changed_passages(encoder, ids: list[str], texts: list[str]):
    """Reuse unchanged text vectors across edits, preserving fresh provenance."""
    if _previous_index is None or _previous_index[2] is None:
        return _encode_documents(encoder, texts, progress=False)
    old_ids, old_texts, old_vectors = _previous_index
    assert old_vectors is not None
    lookup = {
        (person, text): i for i, (person, text) in enumerate(zip(old_ids, old_texts, strict=True))
    }
    previous = [lookup.get((person, text)) for person, text in zip(ids, texts, strict=True)]
    missing = [index for index, old in enumerate(previous) if old is None]
    if len(missing) == len(texts):
        return _encode_documents(encoder, texts, progress=False)
    vectors = np.empty((len(texts), old_vectors.shape[1]), dtype=old_vectors.dtype)
    for index, old in enumerate(previous):
        if old is not None:
            vectors[index] = old_vectors[old]
    if missing:
        vectors[missing] = _encode_documents(encoder, [texts[i] for i in missing], progress=False)
    return vectors


def build_embeddings() -> None:
    """Build/load complete token-bounded passages, invalidating old biography caches."""
    global \
        _encoder, \
        _embeddings, \
        _embedding_ids, \
        _embedding_texts, \
        _embedding_evidence, \
        _lexical, \
        _previous_index
    _encoder = None
    _embeddings = None
    _embedding_ids = []
    _embedding_texts = []
    _embedding_evidence = []
    _lexical = None
    _previous_index = None
    if not is_enabled():
        return
    if _load_cache():
        _lexical = BM25(_embedding_texts)
        _remember_index()
        return
    try:
        encoder = _new_encoder()
    except ImportError:
        logger.warning("sentence-transformers not installed; semantic search unavailable")
        return
    ids, texts, evidence = _collect_passages(encoder)
    if not texts:
        return
    embeddings = _encode_documents(encoder, texts, progress=True)
    _encoder, _embeddings = encoder, embeddings
    _embedding_ids, _embedding_texts, _embedding_evidence = ids, texts, evidence
    _lexical = BM25(texts)
    _remember_index()
    _save_cache()
    logger.info("Indexed %s passages for %s people", len(ids), len(set(ids)))


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        options: dict = {}
        if RERANKER_NAME.startswith("Qwen/Qwen3-Reranker"):
            options = {
                "prompts": {
                    "genealogy": (
                        "Determine whether the Record subject personally satisfies every requirement "
                        "of the genealogy query. Facts about relatives or other people must not be "
                        "attributed to the Record subject. Reject records with the wrong subject, "
                        "negation, dates, places, or event order."
                    )
                },
                "default_prompt_name": "genealogy",
            }
        _reranker = CrossEncoder(
            RERANKER_NAME,
            revision=RERANKER_REVISION,
            device=os.getenv("SEMANTIC_DEVICE", "cpu"),
            cache_folder=os.getenv("SEMANTIC_MODEL_CACHE"),
            max_length=512,
            **options,
        )
    return _reranker


@state.synchronized
def _semantic_search(query: str, max_results: int = 20) -> dict:
    """Hybrid passage retrieval, bounded person reranking, and matching evidence.

    Scores are ranking signals, not calibrated probabilities or factual proof.
    Relationships and exact date/count constraints still require structured checks.
    """
    global _encoder, _lexical
    if not is_enabled():
        return {"error": "Semantic search not enabled", "results": []}
    if _embeddings is None or not _embedding_ids:
        return {"error": "Embeddings not built", "results": []}
    if not query.strip():
        return {"error": "Query must not be empty", "results": []}
    max_results = min(max(1, max_results), 100)
    if _encoder is None:
        try:
            _encoder = _new_encoder()
        except ImportError:
            return {"error": "sentence-transformers not installed", "results": []}
    query_options = {}
    if MODEL_NAME.startswith("BAAI/bge-"):
        query_options["prompt"] = "Represent this sentence for searching relevant passages: "
    elif MODEL_NAME.startswith("Qwen/Qwen3-Embedding"):
        query_options["prompt"] = (
            "Instruct: Retrieve genealogy passages describing individuals satisfying the query.\nQuery: "
        )
    query_embedding = _encoder.encode_query(
        [query], normalize_embeddings=True, convert_to_numpy=True, **query_options
    )[0]
    dense = np.dot(_embeddings, query_embedding)
    if _lexical is None or _lexical.texts is not _embedding_texts:
        _lexical = BM25(_embedding_texts)
    lexical = _lexical.scores(query)
    # Each branch gets a fixed minimum candidate budget. RRF avoids comparing
    # incompatible cosine/BM25 scales and does not favor verbose biographies.
    budget = max(100, max_results * 4)
    fused: dict[int, float] = {}
    person_fused: dict[str, float] = {}
    for scores in (dense, lexical):
        ranked = diverse_top_indices(scores, _embedding_ids, budget)
        seen_people = set()
        for rank, index in enumerate(ranked, start=1):
            if scores is lexical and scores[index] <= 0:
                continue
            fused[index] = fused.get(index, 0.0) + 1 / (60 + rank)
            person = _embedding_ids[index]
            if person not in seen_people:
                seen_people.add(person)
                person_fused[person] = person_fused.get(person, 0.0) + 1 / (60 + len(seen_people))
    passages_by_person: dict[str, list[int]] = {}
    for index in sorted(fused, key=lambda i: (-fused[i], i)):
        person = _embedding_ids[index]
        if person not in state.individuals:
            continue
        passages_by_person.setdefault(person, []).append(index)
    candidate_count = max(
        max_results, min(200, max(1, int(os.getenv("SEMANTIC_RERANK_CANDIDATES", "20"))))
    )
    people = sorted(passages_by_person, key=lambda person: (-person_fused[person], person))[
        :candidate_count
    ]
    selected = {}
    for person in people:
        passages = passages_by_person[person]
        # Always retain the strongest hybrid passage, including paraphrases with
        # no literal query terms. Add a second excerpt only when it matches.
        matching = [index for index in passages[1:] if lexical[index] > 0]
        selected[person] = passages[:1] + matching[:1]
    scores_by_person = {person: person_fused[person] for person in people}
    mode, score_type, reranker_error = "hybrid", "reciprocal_rank_fusion", None
    if os.getenv("SEMANTIC_RERANK_ENABLED", "true").lower() == "true" and people:
        try:
            reranker = _get_reranker()
            pairs = [
                (
                    query,
                    f"Record subject: {state.individuals[person].full_name()}.\n"
                    + "Excerpts from this person's genealogy record:\n"
                    + "\n".join(
                        matching_snippet(_embedding_texts[i], query) for i in selected[person]
                    ),
                )
                for person in people
            ]
            scores = np.asarray(
                reranker.predict(pairs, batch_size=4, show_progress_bar=False)
            ).reshape(-1)
            if len(scores) != len(people) or not np.isfinite(scores).all():
                raise ValueError("Invalid reranker output")
            scores_by_person = dict(zip(people, scores.tolist(), strict=True))
            mode, score_type = "hybrid_reranked", "cross_encoder_logit"
        except Exception:
            logger.exception("Reranker unavailable; returning hybrid retrieval results")
            reranker_error = "Reranker unavailable; results use hybrid retrieval scores"
    ordered = sorted(people, key=lambda person: (-scores_by_person[person], people.index(person)))
    results = []
    for person in ordered[:max_results]:
        indi = state.individuals[person]
        evidence = []
        for index in selected[person]:
            metadata = (
                _embedding_evidence[index]
                if len(_embedding_evidence) == len(_embedding_ids)
                else {}
            )
            evidence.append({**metadata, "text": _embedding_texts[index]})
        full_text = evidence[0]["text"]
        results.append(
            {
                "individual_id": person,
                "name": indi.full_name(),
                "birth_date": indi.birth_date,
                "death_date": indi.death_date,
                "relevance_score": round(scores_by_person[person], 6),
                "snippet": matching_snippet(full_text, query),
                "evidence": evidence,
            }
        )
    response = {
        "query": query,
        "result_count": len(results),
        "results": results,
        "search_mode": mode,
        "score_type": score_type,
    }
    if reranker_error:
        response["warning"] = reranker_error
    return response


_refresh_running = False


def refresh_after_write(revision: int) -> None:
    """Coalesce edits into one background rebuild; publish only matching content.

    Capture texts under the tree lock, encode outside it. A newer edit discards
    the completed result and repeats against the newest revision.
    """
    global _refresh_running
    import threading

    if not is_enabled():
        return
    with state.TREE_LOCK:
        if _refresh_running:
            return
        _refresh_running = True

    def worker():
        global _encoder, _embeddings, _lexical, _refresh_running
        global _embedding_ids, _embedding_texts, _embedding_evidence
        try:
            encoder = _encoder if _encoder is not None else _new_encoder()
            while True:
                with state.TREE_LOCK:
                    path = state.GEDCOM_FILE
                    ids, texts, evidence = _collect_passages(encoder)
                embeddings = _encode_changed_passages(encoder, ids, texts) if texts else None
                with state.TREE_LOCK:
                    if path != state.GEDCOM_FILE:
                        continue
                    _encoder = encoder
                    _embeddings = embeddings
                    _embedding_ids = ids
                    _embedding_texts = texts
                    _embedding_evidence = evidence
                    _lexical = BM25(texts) if texts else None
                    _remember_index()
                    _save_cache()
                    _refresh_running = False
                    return
        except Exception:
            logger.exception(
                "Semantic rebuild failed; current tree remains unavailable to semantic search"
            )
            with state.TREE_LOCK:
                _refresh_running = False

    threading.Thread(target=worker, name=f"tree-semantic-{revision}", daemon=True).start()
