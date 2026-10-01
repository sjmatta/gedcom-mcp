"""Task-oriented reads for the major-release MCP interface."""

import hashlib
from collections import deque
from typing import Literal

from . import state, writes
from .core import (
    MAX_TREE_NODES,
    _get_individual,
    _get_statistics,
    _normalize_lookup_id,
    _search_individuals,
)
from .narrative import _get_biography
from .relationships import MAX_GRAPH_EDGES, Lineage, _get_parent_families, parent_links
from .semantic import _semantic_search

Relation = Literal["parents", "children", "spouses", "siblings", "ancestors", "descendants"]


def snapshot_metadata(expected_snapshot: str | None = None) -> dict:
    store = writes.store
    data = (
        store.document(store.revision)
        if store
        else (state.GEDCOM_FILE.read_bytes() if state.GEDCOM_FILE else b"")
    )
    token = hashlib.sha256(data).hexdigest()
    if expected_snapshot is not None and token != expected_snapshot:
        raise ValueError("Tree changed; restart the query")
    return {"snapshot": token, "revision": store.revision if store else None}


def tree_context() -> dict:
    from . import semantic, spatial

    return {
        **snapshot_metadata(),
        "home_person": (
            home.to_summary()
            if (home := state.individuals.get(state.HOME_PERSON_ID or ""))
            else None
        ),
        "statistics": _get_statistics(),
        "writes_enabled": writes.store is not None,
        "store": writes.store.status() if writes.store else None,
        "semantic_ready": semantic._embeddings is not None,
        "geocoding": spatial.get_geocoding_status(),
        "research": "Specialized tools: search_tools, then call_research_tool.",
        "changes": "search_tools(category='changes'), prepare_change, review complete diff, apply_tree_change.",
    }


def search_people(query, mode="name", limit=50, expected_snapshot=None):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    meta = snapshot_metadata(expected_snapshot)
    if mode == "semantic":
        return {**meta, "mode": mode, **_semantic_search(query, limit)}
    if mode != "name":
        raise ValueError("mode must be name or semantic")
    return {**meta, "mode": mode, "items": _search_individuals(query, limit), "limit": limit}


def get_people(individual_ids=None, view="summary", expected_snapshot=None):
    meta = snapshot_metadata(expected_snapshot)
    ids = individual_ids if individual_ids is not None else [state.HOME_PERSON_ID]
    if not ids or any(not isinstance(id_, str) or not id_ for id_ in ids):
        raise ValueError("Provide person IDs or configure a home person")
    if view not in {"summary", "record", "biography"}:
        raise ValueError("Unknown person view")
    cap = {"summary": 500, "record": 100, "biography": 20}[view]
    if len(ids) > cap:
        raise ValueError(f"{view} view accepts at most {cap} IDs")
    records = {}
    for id_ in ids:
        normalized = _normalize_lookup_id(str(id_))
        person = state.individuals.get(normalized)
        records[normalized] = (
            None
            if person is None
            else person.to_summary()
            if view == "summary"
            else {
                **(_get_individual(normalized) or {}),
                "events": [event.to_dict() for event in person.events],
            }
            if view == "record"
            else _get_biography(normalized)
        )
    return {**meta, "view": view, "people": records}


def relative_edges(person_id: str, direction: str, lineage: Lineage) -> list[dict]:
    person = state.individuals[person_id]
    edges: list[dict] = []
    if direction in {"parents", "siblings"}:
        for link in parent_links(person_id, lineage):
            family = state.families.get(link.family_id)
            if not family:
                continue
            if direction == "parents":
                members = [(family.husband_id, "HUSB"), (family.wife_id, "WIFE")]
            else:
                for id_ in family.children_ids:
                    if id_ not in state.individuals or id_ == person_id:
                        continue
                    for sibling_link in parent_links(id_, lineage):
                        if sibling_link.family_id == family.id:
                            edges.append(
                                {
                                    "to_id": id_,
                                    "role": "CHIL",
                                    **link.to_dict(),
                                    "sibling_parent_link": sibling_link.to_dict(),
                                }
                            )
                continue
            edges.extend(
                {"to_id": id_, "role": role, **link.to_dict()}
                for id_, role in members
                if id_ in state.individuals
            )
    elif direction in {"children", "spouses"}:
        for family_id in dict.fromkeys(person.families_as_spouse):
            family = state.families.get(family_id)
            if not family or person_id not in {family.husband_id, family.wife_id}:
                continue
            if direction == "spouses":
                spouse = family.wife_id if family.husband_id == person_id else family.husband_id
                if spouse in state.individuals:
                    edges.append(
                        {
                            "to_id": spouse,
                            "family_id": family_id,
                            "marriage_date": family.marriage_date,
                            "marriage_place": family.marriage_place,
                        }
                    )
            else:
                for child_id in family.children_ids:
                    if child_id not in state.individuals:
                        continue
                    edges.extend(
                        {"to_id": child_id, "role": "CHIL", **link.to_dict()}
                        for link in parent_links(child_id, lineage)
                        if link.family_id == family_id
                    )
    return edges


def get_relatives(
    individual_id,
    relation,
    generations=1,
    view="list",
    lineage="default",
    expected_snapshot=None,
    offset=0,
    limit=100,
    max_nodes=1000,
):
    meta = snapshot_metadata(expected_snapshot)
    if offset < 0 or not 1 <= limit <= 500 or not 1 <= max_nodes <= 50000:
        raise ValueError("Use nonnegative offset, limit 1–500 and max_nodes 1–50000")
    if view == "tree" and offset != 0:
        raise ValueError("tree view does not accept a pagination offset")
    node_budget = min(max_nodes, MAX_TREE_NODES)
    root = _normalize_lookup_id(individual_id)
    if root not in state.individuals:
        raise ValueError("Individual not found")
    if relation not in {"parents", "children", "spouses", "siblings", "ancestors", "descendants"}:
        raise ValueError("Unknown relation")
    if lineage not in {"default", "birth", "adopted", "foster", "sealing", "all"}:
        raise ValueError("Unknown lineage selection")
    if view not in {"list", "tree", "terminal"}:
        raise ValueError("Unknown relatives view")
    max_depth = 20 if relation in {"parents", "ancestors"} else 10
    if not 0 <= generations <= max_depth:
        raise ValueError(f"generations must be between 0 and {max_depth}")
    if view == "terminal" and relation not in {"parents", "ancestors"}:
        raise ValueError("terminal view requires ancestors or parents")
    direction = {"ancestors": "parents", "descendants": "children"}.get(relation, relation)
    base = {
        **meta,
        "relation": relation,
        "generations": generations,
        "lineage": lineage,
        "view": view,
        "parent_families": _get_parent_families(root),
        "note": "Recorded family links; pedigree qualifiers do not prove genetic parentage.",
    }
    edge_count = 0

    def bounded_edges(id_):
        nonlocal edge_count
        edges = relative_edges(id_, direction, lineage)
        edge_count += len(edges)
        if edge_count > MAX_GRAPH_EDGES:
            raise ValueError("Relatives incomplete: edge budget exceeded; reduce generations")
        return edges

    if view == "tree":
        seen = set()
        count = 0

        def build(id_, level):
            nonlocal count
            count += 1
            if count > node_budget:
                raise ValueError("Relatives incomplete: node budget exceeded; reduce generations")
            result = {**state.individuals[id_].to_summary(), "level": level}
            if id_ in seen:
                return {**result, "repeated_reference": True}
            seen.add(id_)
            edges = bounded_edges(id_)
            result["depth_limited"] = level == generations and bool(edges)
            result["relatives"] = (
                [{"link": edge, "person": build(edge["to_id"], level + 1)} for edge in edges]
                if level < generations
                else []
            )
            return result

        return {**base, "tree": build(root, 0)}
    seen = {root}
    queue: deque[tuple[str, int, list[dict]]] = deque([(root, 0, [])])
    items = []
    depth_limited = False
    while queue:
        current, level, path = queue.popleft()
        edges = bounded_edges(current)
        if view == "terminal" and current != root and not edges:
            items.append({**state.individuals[current].to_summary(), "level": level, "path": path})
        if level == generations:
            depth_limited |= bool(edges)
            continue
        for edge in edges:
            id_ = edge["to_id"]
            if id_ in seen:
                continue
            if len(seen) >= node_budget:
                raise ValueError("Relatives incomplete: node budget exceeded; reduce generations")
            seen.add(id_)
            next_path = [*path, {"from_id": current, "direction": direction, **edge}]
            queue.append((id_, level + 1, next_path))
            if view == "list":
                items.append(
                    {**state.individuals[id_].to_summary(), "level": level, "path": next_path}
                )
    return {
        **base,
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(items) else None,
        "depth_limited": depth_limited,
    }
